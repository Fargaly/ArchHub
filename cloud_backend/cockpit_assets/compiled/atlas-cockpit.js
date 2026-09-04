function _typeof(o) { "@babel/helpers - typeof"; return _typeof = "function" == typeof Symbol && "symbol" == typeof Symbol.iterator ? function (o) { return typeof o; } : function (o) { return o && "function" == typeof Symbol && o.constructor === Symbol && o !== Symbol.prototype ? "symbol" : typeof o; }, _typeof(o); }
function _createForOfIteratorHelper(r, e) { var t = "undefined" != typeof Symbol && r[Symbol.iterator] || r["@@iterator"]; if (!t) { if (Array.isArray(r) || (t = _unsupportedIterableToArray(r)) || e && r && "number" == typeof r.length) { t && (r = t); var _n = 0, F = function F() {}; return { s: F, n: function n() { return _n >= r.length ? { done: !0 } : { done: !1, value: r[_n++] }; }, e: function e(r) { throw r; }, f: F }; } throw new TypeError("Invalid attempt to iterate non-iterable instance.\nIn order to be iterable, non-array objects must have a [Symbol.iterator]() method."); } var o, a = !0, u = !1; return { s: function s() { t = t.call(r); }, n: function n() { var r = t.next(); return a = r.done, r; }, e: function e(r) { u = !0, o = r; }, f: function f() { try { a || null == t["return"] || t["return"](); } finally { if (u) throw o; } } }; }
function _toConsumableArray(r) { return _arrayWithoutHoles(r) || _iterableToArray(r) || _unsupportedIterableToArray(r) || _nonIterableSpread(); }
function _nonIterableSpread() { throw new TypeError("Invalid attempt to spread non-iterable instance.\nIn order to be iterable, non-array objects must have a [Symbol.iterator]() method."); }
function _iterableToArray(r) { if ("undefined" != typeof Symbol && null != r[Symbol.iterator] || null != r["@@iterator"]) return Array.from(r); }
function _arrayWithoutHoles(r) { if (Array.isArray(r)) return _arrayLikeToArray(r); }
function ownKeys(e, r) { var t = Object.keys(e); if (Object.getOwnPropertySymbols) { var o = Object.getOwnPropertySymbols(e); r && (o = o.filter(function (r) { return Object.getOwnPropertyDescriptor(e, r).enumerable; })), t.push.apply(t, o); } return t; }
function _objectSpread(e) { for (var r = 1; r < arguments.length; r++) { var t = null != arguments[r] ? arguments[r] : {}; r % 2 ? ownKeys(Object(t), !0).forEach(function (r) { _defineProperty(e, r, t[r]); }) : Object.getOwnPropertyDescriptors ? Object.defineProperties(e, Object.getOwnPropertyDescriptors(t)) : ownKeys(Object(t)).forEach(function (r) { Object.defineProperty(e, r, Object.getOwnPropertyDescriptor(t, r)); }); } return e; }
function _defineProperty(e, r, t) { return (r = _toPropertyKey(r)) in e ? Object.defineProperty(e, r, { value: t, enumerable: !0, configurable: !0, writable: !0 }) : e[r] = t, e; }
function _toPropertyKey(t) { var i = _toPrimitive(t, "string"); return "symbol" == _typeof(i) ? i : i + ""; }
function _toPrimitive(t, r) { if ("object" != _typeof(t) || !t) return t; var e = t[Symbol.toPrimitive]; if (void 0 !== e) { var i = e.call(t, r || "default"); if ("object" != _typeof(i)) return i; throw new TypeError("@@toPrimitive must return a primitive value."); } return ("string" === r ? String : Number)(t); }
function _slicedToArray(r, e) { return _arrayWithHoles(r) || _iterableToArrayLimit(r, e) || _unsupportedIterableToArray(r, e) || _nonIterableRest(); }
function _nonIterableRest() { throw new TypeError("Invalid attempt to destructure non-iterable instance.\nIn order to be iterable, non-array objects must have a [Symbol.iterator]() method."); }
function _unsupportedIterableToArray(r, a) { if (r) { if ("string" == typeof r) return _arrayLikeToArray(r, a); var t = {}.toString.call(r).slice(8, -1); return "Object" === t && r.constructor && (t = r.constructor.name), "Map" === t || "Set" === t ? Array.from(r) : "Arguments" === t || /^(?:Ui|I)nt(?:8|16|32)(?:Clamped)?Array$/.test(t) ? _arrayLikeToArray(r, a) : void 0; } }
function _arrayLikeToArray(r, a) { (null == a || a > r.length) && (a = r.length); for (var e = 0, n = Array(a); e < a; e++) n[e] = r[e]; return n; }
function _iterableToArrayLimit(r, l) { var t = null == r ? null : "undefined" != typeof Symbol && r[Symbol.iterator] || r["@@iterator"]; if (null != t) { var e, n, i, u, a = [], f = !0, o = !1; try { if (i = (t = t.call(r)).next, 0 === l) { if (Object(t) !== t) return; f = !1; } else for (; !(f = (e = i.call(t)).done) && (a.push(e.value), a.length !== l); f = !0); } catch (r) { o = !0, n = r; } finally { try { if (!f && null != t["return"] && (u = t["return"](), Object(u) !== u)) return; } finally { if (o) throw n; } } return a; } }
function _arrayWithHoles(r) { if (Array.isArray(r)) return r; }
// atlas-cockpit.jsx — THE FOUNDER COCKPIT. A hierarchical wired graph of the whole system.
// MACRO (14 wired domains) → open a domain → its real member nodes + wires →
// open a node → its ego-graph of real connections. Central map + permanent control
// panels (left = VIEW, right = ACT). Vellum drafting aesthetic. Built from real data.

var _window = window,
  HB = _window.HB,
  hsc = _window.hsc,
  HBtn = _window.HBtn,
  HIconBtn = _window.HIconBtn,
  HPill = _window.HPill,
  HDot = _window.HDot,
  HAvatar = _window.HAvatar,
  MapCanvas = _window.MapCanvas,
  STC = _window.STC,
  catCol = _window.catCol,
  SEED_DB = _window.SEED_DB,
  ckLoad = _window.ckLoad,
  ckSave = _window.ckSave;

// v6: no imposed classification. Domains sit where they are put and snap to M.grid; any
// meaning in the layout is the founder's, expressed by moving and grouping them. Bumping
// the key so an older saved layout can't mask the change; earlier keys stay, unread.
var ALS = 'archhub.atlas.v7';
var aLoad = function aLoad() {
  try {
    return JSON.parse(localStorage.getItem(ALS));
  } catch (e) {
    return null;
  }
};
var aSave = function aSave(o) {
  try {
    localStorage.setItem(ALS, JSON.stringify(o));
  } catch (e) {}
};
var STATUS_ORDER = ['live', 'partial', 'prototype', 'planned', 'vision', 'blocked', 'deprecated'];
var CAT_LIST = ['ai', 'skill', 'connector', 'logic', 'custom', 'output', 'input', 'trigger', 'compose', 'transform', 'host', 'agent', 'watch', 'note'];
var DOM_COLS = ['#d97757', '#5fb3b3', '#7898d6', '#a98cd6', '#7ec18e', '#e5b25a', '#6a9bcc', '#cc7a52'];

// The connective-tissue palette — same node kinds as the in-app session canvas
// (stem-core grammar): typed inputs, sliders, triggers, floating rules, watchers,
// adapters (data-type translation), global-param containers, notes.
var STEM_KINDS = [{
  kind: 'input',
  cat: 'input',
  glyph: '◇',
  title: 'Input',
  sub: 'typed value source',
  params: [{
    k: 'value',
    v: 'Tower A'
  }]
}, {
  kind: 'slider',
  cat: 'slider',
  glyph: '▤',
  title: 'Slider',
  sub: 'number 0–1',
  params: [{
    k: 'value',
    v: '0.7'
  }, {
    k: 'min',
    v: '0'
  }, {
    k: 'max',
    v: '1'
  }]
}, {
  kind: 'trigger',
  cat: 'trigger',
  glyph: '▷',
  title: 'Trigger',
  sub: 'emits exec on an event',
  params: [{
    k: 'on',
    v: 'on save'
  }]
}, {
  kind: 'rule',
  cat: 'rule',
  glyph: '⌥',
  title: 'Rule',
  sub: 'floating if / branch',
  params: [{
    k: 'when',
    v: 'value > 0'
  }]
}, {
  kind: 'watch',
  cat: 'watch',
  glyph: '◉',
  title: 'Watch',
  sub: 'passthrough viewer',
  params: [{
    k: 'as',
    v: 'table'
  }]
}, {
  kind: 'adapter',
  cat: 'adapter',
  glyph: '⇄',
  title: 'Adapter',
  sub: 'data-type translation',
  params: [{
    k: 'from',
    v: 'any'
  }, {
    k: 'to',
    v: 'any'
  }]
}, {
  kind: 'globals',
  cat: 'globals',
  glyph: '▦',
  title: 'Globals',
  sub: 'shared param container',
  params: [{
    k: 'env',
    v: 'prod'
  }, {
    k: 'region',
    v: 'eu'
  }]
}, {
  kind: 'note',
  cat: 'note',
  glyph: '✎',
  title: 'Note',
  sub: 'annotation',
  params: []
}];

// SCALE LADDER — everything is a NODE. A CELL (a parameter / value container) composes a
// NODE; nodes group into a DOMAIN; domains group into a FIELD. Stop there. A skill is just
// a saved field, a workflow a saved canvas — every grouping collapses back into a node.
// A group's name should describe its contents, not be a placeholder the founder must fix.
// Prefer a word the members genuinely share; fall back to naming them.
var AH_STOP = new Set(['the', 'and', 'a', 'of', 'system', 'systems', 'engine', 'layer']);
function deriveGroupName(titles) {
  var list = titles.filter(Boolean);
  if (!list.length) return 'Group';
  var wordsOf = function wordsOf(t) {
    return String(t).split(/[^A-Za-z0-9]+/).filter(function (w) {
      return w.length > 2 && !AH_STOP.has(w.toLowerCase());
    });
  };
  var freq = {};
  list.forEach(function (t) {
    return new Set(wordsOf(t).map(function (w) {
      return w.toLowerCase();
    })).forEach(function (w) {
      return freq[w] = (freq[w] || 0) + 1;
    });
  });
  var shared = Object.keys(freq).filter(function (w) {
    return freq[w] >= Math.max(2, Math.ceil(list.length * 0.6));
  }).sort(function (a, b) {
    return freq[b] - freq[a];
  });
  if (shared.length) {
    var w = shared[0];
    var orig = list.flatMap(wordsOf).find(function (x) {
      return x.toLowerCase() === w;
    }) || w;
    return orig[0].toUpperCase() + orig.slice(1);
  }
  var heads = list.map(function (t) {
    return wordsOf(t)[0] || String(t).trim();
  }).filter(Boolean);
  if (heads.length === 2) return heads.join(' + ');
  return heads.slice(0, 2).join(' + ') + ' +' + (heads.length - 2);
}
function ScaleLadder(_ref) {
  var level = _ref.level,
    onClimb = _ref.onClimb,
    depth = _ref.depth;
  var rungs = [['stage', 'CELL', 'parameter · value'], ['node', 'NODE', 'the building block'], ['domain', 'DOMAIN', 'group of nodes'], ['field', 'FIELD', 'group of domains']];
  // one extra rung per tier of grouping that actually exists above a plain field
  for (var t = 2; t <= Math.max(1, depth || 1); t++) {
    var SUP = ['', '', '²', '³', '⁴', '⁵', '⁶', '⁷', '⁸', '⁹'];
    rungs.push(['field' + t, 'FIELD' + (SUP[t] != null ? SUP[t] : '^' + t), 'group of fields ×' + (t - 1)]);
  }
  return /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      top: 54,
      left: '50%',
      transform: 'translateX(-50%)',
      display: 'flex',
      alignItems: 'center',
      padding: '4px 6px',
      background: HB.card,
      border: "1px solid ".concat(HB.line),
      borderRadius: 10,
      boxShadow: '0 3px 12px rgba(0,0,0,.08)',
      fontFamily: HB.mono,
      zIndex: 6
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 7.5,
      color: HB.inkMute,
      letterSpacing: '0.18em',
      padding: '0 9px 0 5px'
    }
  }, "SCALE"), rungs.map(function (_ref2, i) {
    var _ref3 = _slicedToArray(_ref2, 3),
      k = _ref3[0],
      l = _ref3[1],
      sub = _ref3[2];
    var on = level === k;
    return /*#__PURE__*/React.createElement(React.Fragment, {
      key: k
    }, i > 0 && /*#__PURE__*/React.createElement("span", {
      style: {
        color: HB.inkMute,
        fontSize: 9,
        padding: '0 1px',
        opacity: 0.6
      }
    }, "\u2282"), /*#__PURE__*/React.createElement("button", {
      onClick: function onClick() {
        return onClimb(k);
      },
      title: 'climb to ' + sub,
      style: {
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        gap: 1,
        padding: '4px 10px',
        borderRadius: 7,
        border: "1px solid ".concat(on ? HB.accent : 'transparent'),
        background: on ? HB.accentSoft : 'transparent',
        cursor: 'pointer',
        color: on ? HB.accentHi : HB.inkSoft
      },
      onMouseEnter: function onMouseEnter(e) {
        if (!on) e.currentTarget.style.background = HB.paper2;
      },
      onMouseLeave: function onMouseLeave(e) {
        if (!on) e.currentTarget.style.background = 'transparent';
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 10,
        fontWeight: 700,
        letterSpacing: '0.08em'
      }
    }, l), /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 6.5,
        color: on ? HB.accent : HB.inkMute,
        letterSpacing: '0.02em'
      }
    }, sub)));
  }));
}
function AtlasCockpit() {
  var _React$useState = React.useState(null),
    _React$useState2 = _slicedToArray(_React$useState, 2),
    M = _React$useState2[0],
    setM = _React$useState2[1];
  var _React$useState3 = React.useState(function () {
      return {
        open: new Set(),
        collapsed: new Set()
      };
    }),
    _React$useState4 = _slicedToArray(_React$useState3, 2),
    expanded = _React$useState4[0],
    setExpanded = _React$useState4[1];
  var _React$useState5 = React.useState(function () {
      return new Set();
    }),
    _React$useState6 = _slicedToArray(_React$useState5, 2),
    openNodes = _React$useState6[0],
    setOpenNodes = _React$useState6[1];
  var _React$useState7 = React.useState(function () {
      return new Set();
    }),
    _React$useState8 = _slicedToArray(_React$useState7, 2),
    activeWires = _React$useState8[0],
    setActiveWires = _React$useState8[1];
  var _React$useState9 = React.useState({
      domain: null,
      domains: new Set(),
      nodes: new Set(),
      fields: new Set(),
      field: null,
      wire: null
    }),
    _React$useState0 = _slicedToArray(_React$useState9, 2),
    sel = _React$useState0[0],
    setSel = _React$useState0[1];
  var _React$useState1 = React.useState(''),
    _React$useState10 = _slicedToArray(_React$useState1, 2),
    query = _React$useState10[0],
    setQuery = _React$useState10[1];
  var _React$useState11 = React.useState(false),
    _React$useState12 = _slicedToArray(_React$useState11, 2),
    selMode = _React$useState12[0],
    setSelMode = _React$useState12[1];
  // Domains sitting far outside the cluster: framing ignores them, and we surface a
  // dismissible hint rather than silently re-laying-out the founder's placement.
  // THE LAYOUT OWNER DRIVES THE SIZE SIGNAL.
  // MapCanvas measured itself, so a change that resized only its COLUMN (rails shrinking, a
  // panel collapsing) produced no re-render: label attributes kept the size computed for the
  // old width while the painted scale had already changed — which is what left domain titles
  // at 7px on a narrow map. The cockpit owns this flex row, so it measures the map column and
  // passes the width down as a PROP; a prop change cannot fail to re-render.
  var mapColRef = React.useRef(null);
  var _React$useState13 = React.useState(0),
    _React$useState14 = _slicedToArray(_React$useState13, 2),
    mapW = _React$useState14[0],
    setMapW = _React$useState14[1];
  React.useEffect(function () {
    // Track BOTH dimensions: the SVG scales to fit, so its painted scale changes when the
    // column's HEIGHT changes even if the width is pinned at its floor — signalling width
    // alone left the labels sized for a scale that was no longer being painted.
    var lw = 0,
      lh = 0;
    var read = function read() {
      var el = mapColRef.current;
      if (!el) return;
      var r = el.getBoundingClientRect();
      var w = r.width || 0,
        h = r.height || 0;
      if (!w || !h) return;
      if (Math.abs(w - lw) < 2 && Math.abs(h - lh) < 2) return;
      lw = w;
      lh = h;
      setMapW(Math.round(w) + h / 100000); // one scalar, changes on either axis
    };
    read();
    var ro = new ResizeObserver(read);
    ro.observe(document.documentElement);
    if (mapColRef.current) ro.observe(mapColRef.current);
    window.addEventListener('resize', read);
    var poll = setInterval(read, 350);
    return function () {
      ro.disconnect();
      window.removeEventListener('resize', read);
      clearInterval(poll);
    };
  }, []);
  var _React$useState15 = React.useState([]),
    _React$useState16 = _slicedToArray(_React$useState15, 2),
    offGrid = _React$useState16[0],
    setOffGrid = _React$useState16[1];
  var _React$useState17 = React.useState(false),
    _React$useState18 = _slicedToArray(_React$useState17, 2),
    offGridDismissed = _React$useState18[0],
    setOffGridDismissed = _React$useState18[1];
  var _React$useState19 = React.useState(null),
    _React$useState20 = _slicedToArray(_React$useState19, 2),
    vis = _React$useState20[0],
    setVis = _React$useState20[1];
  var _React$useState21 = React.useState(function () {
      return aLoad() && aLoad().assign || {};
    }),
    _React$useState22 = _slicedToArray(_React$useState21, 2),
    assign = _React$useState22[0],
    setAssign = _React$useState22[1];
  var _React$useState23 = React.useState(null),
    _React$useState24 = _slicedToArray(_React$useState23, 2),
    toast = _React$useState24[0],
    setToast = _React$useState24[1];
  var _React$useState25 = React.useState(''),
    _React$useState26 = _slicedToArray(_React$useState25, 2),
    cmd = _React$useState26[0],
    setCmd = _React$useState26[1];
  var _React$useState27 = React.useState(false),
    _React$useState28 = _slicedToArray(_React$useState27, 2),
    domModal = _React$useState28[0],
    setDomModal = _React$useState28[1];
  var _React$useState29 = React.useState(null),
    _React$useState30 = _slicedToArray(_React$useState29, 2),
    ctx = _React$useState30[0],
    setCtx = _React$useState30[1]; // {type:'node'|'wire', id, a, b, x, y}
  var _React$useState31 = React.useState(null),
    _React$useState32 = _slicedToArray(_React$useState31, 2),
    confirmDel = _React$useState32[0],
    setConfirmDel = _React$useState32[1]; // { ids }
  var _React$useState33 = React.useState('library'),
    _React$useState34 = _slicedToArray(_React$useState33, 2),
    leftTab = _React$useState34[0],
    setLeftTab = _React$useState34[1]; // library | agents | index | view
  var canvas = React.useRef(null);
  var tRef = React.useRef(null);
  var _React$useState35 = React.useState(function () {
      return ckLoad() || SEED_DB();
    }),
    _React$useState36 = _slicedToArray(_React$useState35, 2),
    cdb = _React$useState36[0],
    setCdb = _React$useState36[1];
  React.useEffect(function () {
    ckSave(cdb);
  }, [cdb]);
  var setColl = function setColl(coll, fn) {
    return setCdb(function (d) {
      return _objectSpread(_objectSpread({}, d), {}, _defineProperty({}, coll, fn(d[coll])));
    });
  };
  var flash = function flash(m) {
    setToast(m);
    clearTimeout(tRef.current);
    tRef.current = setTimeout(function () {
      return setToast(null);
    }, 2000);
  };
  React.useEffect(function () {
    if (window.applyHBTheme) window.applyHBTheme('dark'); // cockpit is dark-only — single user
    var saved = aLoad();
    // The cockpit IS the graph. When the founder's running application has pushed its
    // projection (the server marks it ATLAS_LIVE), that push is the content; the saved
    // snapshot contributes only what the founder did to the layout -- node and domain
    // positions, and anything he added that the push does not know. Before this, a saved
    // snapshot silently outranked the live push and the map showed yesterday's graph.
    var live = window.ATLAS_LIVE ? window.ATLAS_MAP : null;
    var mergeLive = function mergeLive(L, S) {
      if (!S || !S.nodes) return L;
      var sn = {};
      (S.nodes || []).forEach(function (n) {
        return sn[n.id] = n;
      });
      var sd = {};
      (S.domains || []).forEach(function (d) {
        return sd[d.key] = d;
      });
      var ln = new Set((L.nodes || []).map(function (n) {
          return n.id;
        })),
        ld = new Set((L.domains || []).map(function (d) {
          return d.key;
        }));
      // A saved domain is the SAME domain as a live one when only the graph prefix differs
      // ("gm:domain:ui" vs "ui"): it is layout for the live card, never a second card.
      var same = function same(k) {
        return ld.has(k) || ld.has(String(k).replace(/^gm:domain:/, '')) || ld.has('gm:domain:' + k);
      };
      var domains = (L.domains || []).map(function (d) {
        return sd[d.key] ? _objectSpread(_objectSpread({}, d), {}, {
          x: sd[d.key].x,
          y: sd[d.key].y,
          w: sd[d.key].w,
          h: sd[d.key].h
        }) : d;
      }).concat((S.domains || []).filter(function (d) {
        return !same(d.key);
      }));
      var keptDoms = new Set(domains.map(function (d) {
        return d.key;
      }));
      var nodes = (L.nodes || []).map(function (n) {
        return sn[n.id] ? _objectSpread(_objectSpread({}, n), {}, {
          x: sn[n.id].x,
          y: sn[n.id].y
        }) : n;
      }).concat((S.nodes || []).filter(function (n) {
        return !ln.has(n.id) && keptDoms.has(n.dom);
      }));
      var ids = new Set(nodes.map(function (n) {
        return n.id;
      }));
      var lw = new Set((L.wires || []).map(function (w) {
        return w.a + '|' + w.b;
      }));
      var wires = (L.wires || []).concat((S.wires || []).filter(function (w) {
        return !lw.has(w.a + '|' + w.b) && ids.has(w.a) && ids.has(w.b);
      }));
      return _objectSpread(_objectSpread({}, L), {}, {
        nodes: nodes,
        domains: domains,
        wires: wires,
        fields: S.fields || L.fields,
        grid: L.grid || S.grid
      });
    };
    var data = live ? mergeLive(live, saved && saved.M) : saved && saved.M || window.ATLAS_MAP || {
      domains: [],
      nodes: [],
      wires: [],
      w: 2448,
      h: 2348
    };
    // Attention is a real seed NODE (importance is a node, not a hardcoded rule) and it is
    // WIRED. This is a safety-net only — re-mints the node and/or its wires for any saved
    // state that predates them, so stale localStorage never shows Attention floating loose.
    if (!data.nodes.some(function (n) {
      return n.cat === 'attention';
    })) {
      var d = data.domains.find(function (x) {
        return x.key === 'cockpit';
      }) || data.domains[0];
      if (d) data = _objectSpread(_objectSpread({}, data), {}, {
        nodes: [].concat(_toConsumableArray(data.nodes), [{
          id: 'sys_attention',
          dom: d.key,
          cat: 'attention',
          title: 'Attention',
          sub: 'ranks what needs the founder now — importance is a node, not a hardcoded rule (its params are the weights)',
          status: 'live',
          params: [{
            k: 'weight.blocked',
            v: '3'
          }, {
            k: 'weight.gap',
            v: '2'
          }, {
            k: 'weight.agent',
            v: '1'
          }, {
            k: 'gap.threshold',
            v: '4'
          }],
          evidence_ref: 'self:right-panel/activity',
          x: d.x + 320,
          y: d.y + 72
        }])
      });
    }
    if (data.nodes.some(function (n) {
      return n.id === 'sys_attention';
    }) && !data.wires.some(function (w) {
      return w.a === 'sys_attention' || w.b === 'sys_attention';
    })) {
      var has = function has(id) {
        return data.nodes.some(function (n) {
          return n.id === id;
        });
      };
      var inbound = [['cockpit_agent_loop', 'agent activity → weight.agent'], ['cockpit_live_metrics', 'metric gaps → weight.gap'], ['cockpit_audit_log', 'recent events to rank'], ['connectors_self_heal', 'heal/blocked signals → weight.blocked'], ['connectors_health_daemon', 'fleet health → blocked signal'], ['brain_daemon', 'brain activity to surface']];
      var outbound = [['cockpit_command_bar', 'ranked "what matters now" surfaces here'], ['cockpit_gate', 'high-rank items gate the founder view']];
      var add = [];
      inbound.forEach(function (_ref4) {
        var _ref5 = _slicedToArray(_ref4, 2),
          s = _ref5[0],
          why = _ref5[1];
        if (has(s)) add.push({
          a: s,
          b: 'sys_attention',
          why: why,
          dom: 'cockpit'
        });
      });
      outbound.forEach(function (_ref6) {
        var _ref7 = _slicedToArray(_ref6, 2),
          t = _ref7[0],
          why = _ref7[1];
        if (has(t)) add.push({
          a: 'sys_attention',
          b: t,
          why: why,
          dom: 'cockpit'
        });
      });
      if (add.length) data = _objectSpread(_objectSpread({}, data), {}, {
        wires: [].concat(_toConsumableArray(data.wires), add)
      });
    }
    // The layout grid is structural, not user data: adopt it from the seed if a saved state
    // predates it, so domain drags snap and the off-cell test works on existing layouts.
    if (!data.grid && window.ATLAS_MAP && window.ATLAS_MAP.grid) data = _objectSpread(_objectSpread({}, data), {}, {
      grid: window.ATLAS_MAP.grid
    });
    // Layout footprint is structure, not content: if the seed's arrangement has changed shape
    // since this snapshot was written, take the seed's positions for the SEEDED domains and
    // shift their nodes with them. Anything the founder added or grouped keeps its own place.
    var seed = window.ATLAS_MAP;
    if (seed && seed.domains) {
      var fp = function fp(m) {
        var g = m.grid;
        if (!g) return '';
        return m.domains.map(function (d) {
          return Math.round((d.x - g.x0) / g.px) + ',' + Math.round((d.y - g.y0) / g.py);
        }).sort().join(' ');
      };
      var seededKeys = new Set(seed.domains.map(function (d) {
        return d.key;
      }));
      var savedSeeded = _objectSpread(_objectSpread({}, data), {}, {
        domains: data.domains.filter(function (d) {
          return seededKeys.has(d.key);
        })
      });
      if (fp(savedSeeded) !== fp(seed)) {
        var at = {};
        seed.domains.forEach(function (d) {
          return at[d.key] = d;
        });
        var shift = {};
        var domains = data.domains.map(function (d) {
          var s = at[d.key];
          if (!s) return d;
          shift[d.key] = {
            dx: s.x - d.x,
            dy: s.y - d.y
          };
          return _objectSpread(_objectSpread({}, d), {}, {
            x: s.x,
            y: s.y,
            w: s.w,
            h: s.h
          });
        });
        var nodes = data.nodes.map(function (nd) {
          var s = shift[nd.dom];
          return s ? _objectSpread(_objectSpread({}, nd), {}, {
            x: nd.x + s.dx,
            y: nd.y + s.dy
          }) : nd;
        });
        data = _objectSpread(_objectSpread({}, data), {}, {
          domains: domains,
          nodes: nodes,
          grid: seed.grid
        });
      }
    }
    // placeholder-named groups predate derived naming — name them from their members
    if ((data.fields || []).some(function (f) {
      return /^New (super )?field$/.test(f.title || '');
    })) {
      var byId = {};
      (data.fields || []).forEach(function (f) {
        return byId[f.id] = f;
      });
      data = _objectSpread(_objectSpread({}, data), {}, {
        fields: data.fields.map(function (f) {
          return /^New (super )?field$/.test(f.title || '') ? _objectSpread(_objectSpread({}, f), {}, {
            title: deriveGroupName([].concat(_toConsumableArray((f.domKeys || []).map(function (k) {
              return (data.domains.find(function (d) {
                return d.key === k;
              }) || {}).title;
            })), _toConsumableArray((f.fieldIds || []).map(function (k) {
              return (byId[k] || {}).title;
            }))))
          }) : f;
        })
      });
    }
    // Two domains in one grid cell draw on top of each other. Whatever put them there
    // (a stale snapshot, a push laid out on the same lattice), the later arrival moves to
    // the next free cell and its nodes move with it -- the map is never unreadable.
    if (data.grid && data.domains.length) {
      var g = data.grid,
        used = new Set(),
        shifted = {};
      var cell = function cell(i) {
        return i % 4 + ',' + Math.floor(i / 4);
      };
      var _domains = data.domains.map(function (d) {
        var c = Math.round((d.x - g.x0) / g.px) + ',' + Math.round((d.y - g.y0) / g.py);
        if (!used.has(c)) {
          used.add(c);
          return d;
        }
        var i = 0;
        while (used.has(cell(i))) i++;
        used.add(cell(i));
        var nx = g.x0 + i % 4 * g.px,
          ny = g.y0 + Math.floor(i / 4) * g.py;
        shifted[d.key] = {
          dx: nx - d.x,
          dy: ny - d.y
        };
        return _objectSpread(_objectSpread({}, d), {}, {
          x: nx,
          y: ny
        });
      });
      if (Object.keys(shifted).length) data = _objectSpread(_objectSpread({}, data), {}, {
        domains: _domains,
        nodes: data.nodes.map(function (n) {
          return shifted[n.dom] ? _objectSpread(_objectSpread({}, n), {}, {
            x: n.x + shifted[n.dom].dx,
            y: n.y + shifted[n.dom].dy
          }) : n;
        })
      });
    }
    setM(data);
    setVis({
      domains: new Set(data.domains.map(function (d) {
        return d.key;
      })),
      status: new Set(STATUS_ORDER),
      wires: true,
      params: true,
      labels: true
    });
  }, []);
  React.useEffect(function () {
    if (M) aSave({
      M: M,
      assign: assign
    });
  }, [M, assign]);

  // ── attention layer: a NODE computes importance (its params are the weights) ──
  var attention = React.useMemo(function () {
    if (!M) return [];
    var dn = function dn(k) {
      return (M.domains.find(function (d) {
        return d.key === k;
      }) || {}).title || k;
    };
    var att = M.nodes.find(function (n) {
      return n.cat === 'attention';
    });
    var pv = function pv(k, d) {
      var p = (att && att.params || []).find(function (x) {
        return x.k === k;
      });
      return p ? parseFloat(p.v) || d : d;
    };
    var W = {
      blocked: pv('weight.blocked', 3),
      gap: pv('weight.gap', 2),
      agent: pv('weight.agent', 1)
    };
    var gapMin = pv('gap.threshold', 4);
    var items = [];
    M.nodes.filter(function (n) {
      return n.status === 'blocked';
    }).forEach(function (n) {
      return items.push({
        kind: 'blocked',
        label: n.title,
        sub: dn(n.dom),
        tone: 'red',
        nodeId: n.id,
        dom: n.dom,
        score: Math.round(W.blocked * 10) / 10
      });
    });
    M.domains.map(function (d) {
      var ms = M.nodes.filter(function (n) {
        return n.dom === d.key;
      });
      var v = ms.filter(function (n) {
        return n.status === 'vision';
      }).length;
      return {
        d: d,
        v: v,
        pct: v / (ms.length || 1)
      };
    }).filter(function (x) {
      return x.v >= gapMin;
    }).sort(function (a, b) {
      return b.v - a.v;
    }).slice(0, 4).forEach(function (x) {
      return items.push({
        kind: 'gap',
        label: x.d.title,
        sub: "".concat(x.v, " unbuilt \xB7 ").concat(Math.round(x.pct * 100), "% vision"),
        tone: 'accent',
        dom: x.d.key,
        score: Math.round(W.gap * x.v * 10) / 10
      });
    });
    // failed runs — a real outcome the founder must see, ranked with blocked weight
    M.nodes.filter(function (n) {
      return n.rt && n.rt.state === 'error';
    }).forEach(function (n) {
      return items.push({
        kind: 'agent',
        label: n.title,
        sub: "run failed \xB7 ".concat(dn(n.dom)),
        tone: 'red',
        nodeId: n.id,
        dom: n.dom,
        score: Math.round(W.blocked * 1.2 * 10) / 10
      });
    });
    // live agent work, ranked by RUNTIME STATE not headcount
    Object.keys(assign).filter(function (id) {
      return (assign[id] || []).length && M.nodes.find(function (n) {
        return n.id === id;
      });
    }).map(function (id) {
      var n = M.nodes.find(function (x) {
        return x.id === id;
      });
      var st = n.rt && n.rt.state || 'idle';
      if (st === 'error') return null; // already reported above
      var live = st === 'running' ? 2.5 : st === 'stale' ? 1.4 : 1;
      return {
        kind: 'agent',
        label: n.title,
        tone: st === 'running' ? 'accent' : 'blue',
        nodeId: id,
        dom: n.dom,
        sub: "".concat(st === 'running' ? 'running now' : st === 'stale' ? 'stale — needs a re-run' : "".concat(assign[id].length, " agent").concat(assign[id].length > 1 ? 's' : ''), " \xB7 ").concat(dn(n.dom)),
        score: Math.round(W.agent * live * assign[id].length * 10) / 10
      };
    }).filter(Boolean).sort(function (a, b) {
      return b.score - a.score;
    }).slice(0, 5).forEach(function (x) {
      return items.push(x);
    });
    // work the graph owes: dependents left stale by an upstream run
    var staleCount = M.nodes.filter(function (n) {
      return n.rt && n.rt.state === 'stale';
    }).length;
    if (staleCount >= 3) items.push({
      kind: 'gap',
      label: "".concat(staleCount, " nodes stale"),
      sub: 'upstream ran — dependents need a re-run',
      tone: 'amber',
      score: Math.round(W.gap * 0.8 * 10) / 10
    });
    return items.sort(function (a, b) {
      return b.score - a.score;
    });
  }, [M, assign]);

  // one tick advances every running node; completion marks dependents stale and lights wires
  React.useEffect(function () {
    if (!M) return; // runs before the loading guard, so M may not exist yet
    var running = M.nodes.filter(function (n) {
      return n.rt && n.rt.state === 'running';
    });
    if (!running.length) return;
    var t = setInterval(function () {
      var done = running.filter(function (n) {
        return Date.now() - (n.rt.since || 0) > 1200;
      });
      if (!done.length) return;
      var doneIds = new Set(done.map(function (n) {
        return n.id;
      }));
      var deps = new Set();
      done.forEach(function (n) {
        return (window.RT ? window.RT.downstream(M, n.id) : []).forEach(function (id) {
          return deps.add(id);
        });
      });
      setM(function (m) {
        return _objectSpread(_objectSpread({}, m), {}, {
          nodes: m.nodes.map(function (n) {
            if (doneIds.has(n.id)) {
              var run = window.RT ? window.RT.mkRun(n) : {
                ok: true,
                t: Date.now()
              };
              var runs = [].concat(_toConsumableArray(n.rt && n.rt.runs || []), [run]);
              // a failed run is a REAL outcome: the node goes blocked and Attention will rank it
              return _objectSpread(_objectSpread({}, n), {}, {
                status: run.ok ? n.status : 'blocked',
                rt: _objectSpread(_objectSpread({}, n.rt), {}, {
                  state: run.ok ? 'fresh' : 'error',
                  runs: runs,
                  last: run
                })
              });
            }
            // dependents of a completed node are stale until they re-run — the graph stays honest
            if (deps.has(n.id) && !(n.rt && n.rt.state === 'running')) return _objectSpread(_objectSpread({}, n), {}, {
              rt: _objectSpread(_objectSpread({}, n.rt || {}), {}, {
                state: 'stale'
              })
            });
            return n;
          })
        });
      });
      // light the wires the work travelled down
      setActiveWires(function (w) {
        var s = new Set(w);
        M.wires.forEach(function (wr, i) {
          if (doneIds.has(wr.a)) s.add(wr.a + '|' + wr.b);
        });
        return s;
      });
      setTimeout(function () {
        return setActiveWires(new Set());
      }, 1600);
      var bad = done.filter(function (n) {
        return n.rt && n.rt.state !== 'error';
      }).length;
      flash("".concat(done.length, " node").concat(done.length > 1 ? 's' : '', " ran \xB7 ").concat(deps.size, " dependent").concat(deps.size === 1 ? '' : 's', " stale"));
    }, 350);
    return function () {
      return clearInterval(t);
    };
  }, [M]);
  if (!M || !vis) return /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'fixed',
      inset: 0,
      display: 'grid',
      placeItems: 'center',
      color: '#9b938a',
      fontFamily: 'monospace',
      fontSize: 13
    }
  }, "loading the grand map\u2026");
  var DB = cdb;
  var counts = {};
  STATUS_ORDER.forEach(function (s) {
    return counts[s] = 0;
  });
  M.nodes.forEach(function (n) {
    return counts[n.status] = (counts[n.status] || 0) + 1;
  });
  var total = M.nodes.length;
  var domName = function domName(k) {
    return (M.domains.find(function (d) {
      return d.key === k;
    }) || {}).title || k;
  };
  var selNodes = M.nodes.filter(function (n) {
    return sel.nodes.has(n.id);
  });

  // ── single-model navigation: zoom + expand/collapse in place ──
  var fitAll = function fitAll() {
    canvas.current && canvas.current.fitAll();
  };
  var toggleDomain = function toggleDomain(key, open) {
    setExpanded(function (e) {
      var o = new Set(e.open),
        c = new Set(e.collapsed);
      if (open) {
        o.add(key);
        c["delete"](key);
      } else {
        c.add(key);
        o["delete"](key);
      }
      return {
        open: o,
        collapsed: c
      };
    });
  };
  var focusDomain = function focusDomain(key) {
    setExpanded(function (e) {
      var o = new Set(e.open);
      o.add(key);
      var c = new Set(e.collapsed);
      c["delete"](key);
      return {
        open: o,
        collapsed: c
      };
    });
    setTimeout(function () {
      return canvas.current && canvas.current.focusDomain(key);
    }, 30);
  };
  var expandAll = function expandAll() {
    return setExpanded({
      open: new Set(M.domains.map(function (d) {
        return d.key;
      })),
      collapsed: new Set()
    });
  };
  var collapseAll = function collapseAll() {
    return setExpanded({
      open: new Set(),
      collapsed: new Set(M.domains.map(function (d) {
        return d.key;
      }))
    });
  };
  // TIDY UP — wire-aware layout, not an alphabetical grid. Domains that talk to each other
  // are placed adjacent (greedy seed + pairwise swap minimising Σ weight × slot distance),
  // then member nodes are laid out by category so reading down a column groups alike work.
  var autoOrganize = function autoOrganize() {
    setM(function (m) {
      var domOfN = {};
      m.nodes.forEach(function (n) {
        return domOfN[n.id] = n.dom;
      });
      var Wt = {};
      m.wires.forEach(function (w) {
        var a = domOfN[w.a],
          b = domOfN[w.b];
        if (a && b && a !== b) {
          var k = [a, b].sort().join('|');
          Wt[k] = (Wt[k] || 0) + 1;
        }
      });
      var wOf = function wOf(a, b) {
        return Wt[[a, b].sort().join('|')] || 0;
      };
      var keys = m.domains.map(function (d) {
        return d.key;
      });
      var COLS = 4,
        ROWS = Math.ceil(keys.length / COLS);
      var slot = function slot(i) {
        return {
          c: i % COLS,
          r: Math.floor(i / COLS)
        };
      };
      var dist = function dist(i, j) {
        var a = slot(i),
          b = slot(j);
        return Math.hypot(a.c - b.c, (a.r - b.r) * 1.15);
      };
      var deg = {};
      keys.forEach(function (k) {
        return deg[k] = keys.reduce(function (s, o) {
          return s + wOf(k, o);
        }, 0);
      });
      var order = _toConsumableArray(keys).sort(function (a, b) {
        return deg[b] - deg[a];
      });
      var placed = {};
      var free = new Set(keys.map(function (_, i) {
        return i;
      }));
      placed[order[0]] = Math.min(5, keys.length - 1);
      free["delete"](placed[order[0]]);
      var _iterator = _createForOfIteratorHelper(order.slice(1)),
        _step;
      try {
        for (_iterator.s(); !(_step = _iterator.n()).done;) {
          var k = _step.value;
          var best = null,
            bestScore = -1;
          var _iterator4 = _createForOfIteratorHelper(free),
            _step4;
          try {
            for (_iterator4.s(); !(_step4 = _iterator4.n()).done;) {
              var s = _step4.value;
              var sc = 0;
              for (var _i = 0, _Object$entries = Object.entries(placed); _i < _Object$entries.length; _i++) {
                var _Object$entries$_i = _slicedToArray(_Object$entries[_i], 2),
                  pk = _Object$entries$_i[0],
                  ps = _Object$entries$_i[1];
                var w = wOf(k, pk);
                if (w) sc += w / (1 + dist(s, ps));
              }
              if (sc > bestScore) {
                bestScore = sc;
                best = s;
              }
            }
          } catch (err) {
            _iterator4.e(err);
          } finally {
            _iterator4.f();
          }
          placed[k] = best;
          free["delete"](best);
        }
      } catch (err) {
        _iterator.e(err);
      } finally {
        _iterator.f();
      }
      var cost = function cost() {
        var c = 0;
        var _iterator2 = _createForOfIteratorHelper(keys),
          _step2;
        try {
          for (_iterator2.s(); !(_step2 = _iterator2.n()).done;) {
            var a = _step2.value;
            var _iterator3 = _createForOfIteratorHelper(keys),
              _step3;
            try {
              for (_iterator3.s(); !(_step3 = _iterator3.n()).done;) {
                var b = _step3.value;
                if (a < b) {
                  var w = wOf(a, b);
                  if (w) c += w * dist(placed[a], placed[b]);
                }
              }
            } catch (err) {
              _iterator3.e(err);
            } finally {
              _iterator3.f();
            }
          }
        } catch (err) {
          _iterator2.e(err);
        } finally {
          _iterator2.f();
        }
        return c;
      };
      for (var pass = 0; pass < 60; pass++) {
        var imp = false;
        for (var i = 0; i < keys.length; i++) for (var j = i + 1; j < keys.length; j++) {
          var a = keys[i],
            b = keys[j];
          var c0 = cost();
          var _ref8 = [placed[b], placed[a]];
          placed[a] = _ref8[0];
          placed[b] = _ref8[1];
          if (cost() >= c0) {
            var _ref9 = [placed[b], placed[a]];
            placed[a] = _ref9[0];
            placed[b] = _ref9[1];
          } else imp = true;
        }
        if (!imp) break;
      }
      // Fixed 560×480 boxes on a 4-wide grid → 2510×2160 overall (aspect 0.86), which
      // matches the canvas safe area, so "frame all" fills it instead of letterboxing.
      var NWl = 152,
        NHl = 86,
        PADX = 24,
        PADT = 64,
        CGAP = 26,
        RGAP = 26,
        GX = 90,
        GY = 80,
        NCOLS = 4;
      var DW = 560,
        DH = 480;
      var catOrder = ['input', 'connector', 'trigger', 'transform', 'logic', 'ai', 'skill', 'compose', 'output', 'watch', 'custom', 'attention'];
      var sized = m.domains.map(function (d) {
        return _objectSpread(_objectSpread({}, d), {}, {
          w: DW,
          h: DH
        });
      });
      var rowH = {},
        colW = {};
      sized.forEach(function (d) {
        var s = slot(placed[d.key]);
        rowH[s.r] = Math.max(rowH[s.r] || 0, d.h);
        colW[s.c] = Math.max(colW[s.c] || 0, d.w);
      });
      var rowY = {},
        colX = {};
      var ya = 40;
      for (var r = 0; r < ROWS; r++) {
        rowY[r] = ya;
        ya += (rowH[r] || DH) + GY;
      }
      var xa = 40;
      for (var c = 0; c < COLS; c++) {
        colX[c] = xa;
        xa += (colW[c] || DW) + GX;
      }
      var domains = sized.map(function (d) {
        var s = slot(placed[d.key]);
        return _objectSpread(_objectSpread({}, d), {}, {
          x: colX[s.c],
          y: rowY[s.r]
        });
      });
      var byKey = {};
      domains.forEach(function (d) {
        return byKey[d.key] = d;
      });
      var nodes = [];
      var byDom = {};
      m.nodes.forEach(function (n) {
        (byDom[n.dom] = byDom[n.dom] || []).push(n);
      });
      Object.entries(byDom).forEach(function (_ref0) {
        var _ref1 = _slicedToArray(_ref0, 2),
          key = _ref1[0],
          ns = _ref1[1];
        var d = byKey[key];
        if (!d) {
          ns.forEach(function (n) {
            return nodes.push(n);
          });
          return;
        }
        var sorted = _toConsumableArray(ns).sort(function (a, b) {
          var ca = catOrder.indexOf(a.cat),
            cb = catOrder.indexOf(b.cat);
          return (ca < 0 ? 99 : ca) - (cb < 0 ? 99 : cb) || String(a.title).localeCompare(String(b.title));
        });
        sorted.forEach(function (n, i) {
          return nodes.push(_objectSpread(_objectSpread({}, n), {}, {
            x: d.x + PADX + i % NCOLS * (NWl + CGAP),
            y: d.y + PADT + Math.floor(i / NCOLS) * (NHl + RGAP)
          }));
        });
      });
      return _objectSpread(_objectSpread({}, m), {}, {
        domains: domains,
        nodes: nodes
      });
    });
    setExpanded({
      open: new Set(),
      collapsed: new Set()
    });
    setOpenNodes(new Set());
    clearSel();
    flash('Tidied — wired domains placed adjacent');
    setTimeout(fitAll, 80);
  };
  var inspectNode = function inspectNode(id) {
    var n = M.nodes.find(function (x) {
      return x.id === id;
    });
    if (n) {
      focusDomain(n.dom);
      setSel({
        domain: null,
        nodes: new Set([id])
      });
      setTimeout(function () {
        return canvas.current && canvas.current.focusNode(id);
      }, 60);
    }
  };
  var toggleNode = function toggleNode(id, open) {
    return setOpenNodes(function (s) {
      var n = new Set(s);
      if (open) n.add(id);else n["delete"](id);
      return n;
    });
  };

  // ── selection ── (everything is a node on the graph: nodes, domains, fields all select the same way)
  var pickDomain = function pickDomain(key, additive) {
    return setSel(function (s) {
      var cur = s.domains || new Set();
      if (additive) {
        var d = new Set(cur);
        d.has(key) ? d["delete"](key) : d.add(key);
        return {
          domain: d.size === 1 ? _toConsumableArray(d)[0] : null,
          domains: d,
          nodes: new Set(),
          fields: new Set(),
          field: null,
          wire: null
        };
      }
      return {
        domain: key,
        domains: new Set([key]),
        nodes: new Set(),
        fields: new Set(),
        field: null,
        wire: null
      };
    });
  };
  var pickField = function pickField(id, additive) {
    return setSel(function (s) {
      var cur = s.fields || new Set();
      if (additive) {
        var f = new Set(cur);
        f.has(id) ? f["delete"](id) : f.add(id);
        return {
          domain: null,
          domains: new Set(),
          nodes: new Set(),
          fields: f,
          field: f.size === 1 ? _toConsumableArray(f)[0] : null
        };
      }
      return {
        domain: null,
        domains: new Set(),
        nodes: new Set(),
        fields: new Set([id]),
        field: id
      };
    });
  };
  var pickNode = function pickNode(id, additive) {
    if (id == null) {
      if (!additive) setSel(function (s) {
        return _objectSpread(_objectSpread({}, s), {}, {
          nodes: new Set()
        });
      });
      return;
    }
    setSel(function (s) {
      var n = new Set(additive ? s.nodes : []);
      if (additive && n.has(id)) n["delete"](id);else n.add(id);
      return {
        domain: additive ? s.domain : null,
        domains: additive ? s.domains || new Set() : new Set(),
        nodes: n,
        field: null
      };
    });
  };
  var onSelectBox = function onSelectBox(ids, additive) {
    return setSel(function (s) {
      var n = new Set(additive ? s.nodes : []);
      ids.forEach(function (i) {
        return n.add(i);
      });
      return _objectSpread(_objectSpread({}, s), {}, {
        domains: additive ? s.domains || new Set() : new Set(),
        nodes: n,
        field: null
      });
    });
  };
  // scale-aware marquee: grabs collapsed DOMAINS + open-domain NODES in one drag (everything is a node)
  var onMarquee = function onMarquee(nodeIds, domKeys, additive) {
    return setSel(function (s) {
      var n = new Set(additive ? s.nodes : []);
      nodeIds.forEach(function (i) {
        return n.add(i);
      });
      var dms = new Set(additive ? s.domains || new Set() : []);
      domKeys.forEach(function (k) {
        return dms.add(k);
      });
      return {
        domain: dms.size === 1 && n.size === 0 ? _toConsumableArray(dms)[0] : null,
        domains: dms,
        nodes: n,
        field: null
      };
    });
  };
  var clearSel = function clearSel() {
    return setSel({
      domain: null,
      domains: new Set(),
      nodes: new Set(),
      fields: new Set(),
      field: null,
      wire: null
    });
  };
  var selectBy = function selectBy(pred) {
    return setSel(function (s) {
      return {
        domain: null,
        domains: new Set(),
        nodes: new Set(M.nodes.filter(pred).map(function (n) {
          return n.id;
        })),
        field: null
      };
    });
  };

  // ── mutations ──
  var patchNode = function patchNode(id, patch) {
    return setM(function (m) {
      return _objectSpread(_objectSpread({}, m), {}, {
        nodes: m.nodes.map(function (n) {
          return n.id === id ? _objectSpread(_objectSpread({}, n), patch) : n;
        })
      });
    });
  };
  // ── runtime: run a node, pulse its wires, mark dependents stale, record history ──
  var setRT = function setRT(id, rt) {
    return setM(function (m) {
      return _objectSpread(_objectSpread({}, m), {}, {
        nodes: m.nodes.map(function (n) {
          return n.id === id ? _objectSpread(_objectSpread({}, n), {}, {
            rt: _objectSpread(_objectSpread({}, n.rt || {
              runs: []
            }), rt)
          }) : n;
        })
      });
    });
  };
  var markStaleDownstream = function markStaleDownstream(id) {
    return setM(function (m) {
      var RT = window.RT;
      var down = new Set(RT.downstream(m, id));
      return _objectSpread(_objectSpread({}, m), {}, {
        nodes: m.nodes.map(function (n) {
          return down.has(n.id) && (!n.rt || n.rt.state !== 'running') ? _objectSpread(_objectSpread({}, n), {}, {
            rt: _objectSpread(_objectSpread({}, n.rt || {
              runs: []
            }), {}, {
              state: 'stale'
            })
          }) : n;
        })
      });
    });
  };
  var runNode = function runNode(id) {
    var RT = window.RT;
    var node = M.nodes.find(function (n) {
      return n.id === id;
    });
    if (!node) return;
    if (node.frozen) {
      flash('Frozen — unfreeze to run');
      return;
    }
    setRT(id, {
      state: 'running'
    });
    var outKeys = M.wires.filter(function (w) {
      return w.a === id;
    }).map(function (w) {
      return w.a + '>' + w.b;
    });
    setActiveWires(new Set(outKeys));
    flash("Running ".concat(node.title, "\u2026"));
    setTimeout(function () {
      var run = RT.mkRun(node);
      setM(function (m) {
        var down = new Set(RT.downstream(m, id));
        return _objectSpread(_objectSpread({}, m), {}, {
          nodes: m.nodes.map(function (n) {
            if (n.id === id) {
              var runs = [].concat(_toConsumableArray(n.rt && n.rt.runs || []), [run]);
              return _objectSpread(_objectSpread({}, n), {}, {
                rt: {
                  state: run.ok ? 'fresh' : 'error',
                  runs: runs,
                  lastRun: run.t
                }
              });
            }
            if (down.has(n.id) && (!n.rt || n.rt.state !== 'running')) return _objectSpread(_objectSpread({}, n), {}, {
              rt: _objectSpread(_objectSpread({}, n.rt || {
                runs: []
              }), {}, {
                state: 'stale'
              })
            });
            return n;
          })
        });
      });
      setActiveWires(new Set());
      flash(run.ok ? "\u2713 ".concat(node.title, " \u2192 ").concat(run.result) : "\u2717 ".concat(node.title, " failed"));
    }, 1100);
  };
  var runVariant = function runVariant(id, fromRun) {
    var RT = window.RT;
    var node = M.nodes.find(function (n) {
      return n.id === id;
    });
    if (!node) return;
    var run = RT.mkRun(node, fromRun.id);
    setRT(id, {
      runs: [].concat(_toConsumableArray(RT.rtRuns(node)), [run]),
      state: run.ok ? 'fresh' : 'error'
    });
    flash("\u2325 variant of run #".concat(fromRun.n));
  };
  var addWatcher = function addWatcher(id) {
    var node = M.nodes.find(function (n) {
      return n.id === id;
    });
    if (!node) return;
    var wid = 'watch_' + Date.now().toString(36);
    setM(function (m) {
      return _objectSpread(_objectSpread({}, m), {}, {
        nodes: [].concat(_toConsumableArray(m.nodes), [{
          id: wid,
          dom: node.dom,
          cat: 'watch',
          title: 'Watch · ' + node.title.slice(0, 14),
          sub: 'live result of ' + node.title,
          status: 'live',
          params: [],
          evidence_ref: '',
          x: node.x + 180,
          y: node.y + 30
        }]),
        wires: [].concat(_toConsumableArray(m.wires), [{
          a: id,
          b: wid,
          why: 'streams its latest result to this watcher',
          kind: 'data'
        }])
      });
    });
    flash('Watcher added → wired');
    setSel({
      domain: null,
      nodes: new Set([wid])
    });
  };
  var patchDomain = function patchDomain(key, patch) {
    return setM(function (m) {
      return _objectSpread(_objectSpread({}, m), {}, {
        domains: m.domains.map(function (d) {
          return d.key === key ? _objectSpread(_objectSpread({}, d), patch) : d;
        })
      });
    });
  };
  var moveNode = function moveNode(id, x, y) {
    return setM(function (m) {
      return _objectSpread(_objectSpread({}, m), {}, {
        nodes: m.nodes.map(function (n) {
          return n.id === id ? _objectSpread(_objectSpread({}, n), {}, {
            x: x,
            y: y
          }) : n;
        })
      });
    });
  };
  // Domain drags SNAP to the published layout grid. A domain is a super-node in a
  // coordinated model, not a free-floating sticky: snapping keeps the macro view tidy and
  // keeps "frame all" tight (a single off-cell box used to inflate the frame ~40% and
  // shrink every label). The domain still goes where you drop it — just aligned.
  // nearest grid cell that no domain occupies — searched outward from the ideal cell
  var freeCell = function freeCell(m, x, y) {
    var g = m.grid;
    if (!g) return {
      x: x,
      y: y
    };
    var taken = new Set(m.domains.map(function (d) {
      return Math.round((d.x - g.x0) / g.px) + ',' + Math.round((d.y - g.y0) / g.py);
    }));
    var c0 = Math.round((x - g.x0) / g.px),
      r0 = Math.round((y - g.y0) / g.py);
    for (var ring = 0; ring < 12; ring++) {
      for (var dc = -ring; dc <= ring; dc++) for (var dr = -ring; dr <= ring; dr++) {
        if (Math.max(Math.abs(dc), Math.abs(dr)) !== ring) continue;
        var cc = c0 + dc,
          rr = r0 + dr;
        if (cc < 0 || rr < 0 || taken.has(cc + ',' + rr)) continue;
        return {
          x: g.x0 + cc * g.px,
          y: g.y0 + rr * g.py
        };
      }
    }
    return {
      x: g.x0 + c0 * g.px,
      y: g.y0 + r0 * g.py
    };
  };
  var snapDomain = function snapDomain(m, x, y) {
    var g = m.grid;
    if (!g) return {
      x: x,
      y: y
    };
    return {
      x: g.x0 + Math.round((x - g.x0) / g.px) * g.px,
      y: g.y0 + Math.round((y - g.y0) / g.py) * g.py
    };
  };
  var moveDomain = function moveDomain(key, dx, dy) {
    return setM(function (m) {
      var d0 = m.domains.find(function (d) {
        return d.key === key;
      });
      if (!d0) return m;
      var s = snapDomain(m, d0.x + dx, d0.y + dy);
      var ax = s.x - d0.x,
        ay = s.y - d0.y; // actual applied delta, after snapping
      return _objectSpread(_objectSpread({}, m), {}, {
        domains: m.domains.map(function (d) {
          return d.key === key ? _objectSpread(_objectSpread({}, d), {}, {
            x: s.x,
            y: s.y
          }) : d;
        }),
        nodes: m.nodes.map(function (n) {
          return n.dom === key ? _objectSpread(_objectSpread({}, n), {}, {
            x: n.x + ax,
            y: n.y + ay
          }) : n;
        })
      });
    });
  };
  var delNodes = function delNodes(ids) {
    var s = new Set(ids);
    setM(function (m) {
      return _objectSpread(_objectSpread({}, m), {}, {
        nodes: m.nodes.filter(function (n) {
          return !s.has(n.id);
        }),
        wires: m.wires.filter(function (w) {
          return !s.has(w.a) && !s.has(w.b);
        })
      });
    });
    clearSel();
    flash("Deleted ".concat(ids.length, " node").concat(ids.length > 1 ? 's' : ''));
  };
  var requestDelete = function requestDelete(ids) {
    if (ids.length) setConfirmDel({
      ids: ids
    });
  };
  // ── graph logic: wire / unwire / freeze / duplicate, via ports + right-click ──
  var connectNodes = function connectNodes(a, b) {
    if (a === b) return;
    var na = M.nodes.find(function (n) {
        return n.id === a;
      }),
      nb = M.nodes.find(function (n) {
        return n.id === b;
      });
    if (!na || !nb) return;
    if (M.wires.some(function (w) {
      return w.a === a && w.b === b;
    })) {
      flash('Already wired');
      return;
    }
    var ta = window.typeOf ? window.typeOf(na) : 'any';
    var tb = window.typeOf ? window.typeOf(nb) : 'any';
    var ok = window.archCanConnect ? window.archCanConnect(ta, tb) : true;
    if (ok) {
      setM(function (m) {
        return _objectSpread(_objectSpread({}, m), {}, {
          wires: [].concat(_toConsumableArray(m.wires), [{
            a: a,
            b: b,
            why: "carries ".concat(ta),
            kind: 'flow',
            t: ta
          }])
        });
      });
      flash(ta === tb ? "Wired \xB7 ".concat(ta) : "Wired \xB7 ".concat(ta, " \u2192 ").concat(tb, " (any bridges)"));
    } else {
      // types differ — the app grammar inserts an ADAPTER that translates ta → tb
      var id = 'adp_' + Date.now().toString(36);
      var mx = Math.round((na.x + nb.x) / 2),
        my = Math.round((na.y + nb.y) / 2);
      setM(function (m) {
        return _objectSpread(_objectSpread({}, m), {}, {
          nodes: [].concat(_toConsumableArray(m.nodes), [{
            id: id,
            dom: na.dom,
            cat: 'adapter',
            title: "".concat(ta, " \u21C4 ").concat(tb),
            sub: 'type translation',
            status: 'live',
            params: [{
              k: 'from',
              v: ta
            }, {
              k: 'to',
              v: tb
            }, {
              k: 'on_fail',
              v: 'coerce'
            }],
            evidence_ref: '',
            x: mx,
            y: my
          }]),
          wires: [].concat(_toConsumableArray(m.wires), [{
            a: a,
            b: id,
            why: "emits ".concat(ta),
            kind: 'flow',
            t: ta
          }, {
            a: id,
            b: b,
            why: "translated to ".concat(tb),
            kind: 'flow',
            t: tb
          }])
        });
      });
      setSel({
        domain: null,
        nodes: new Set([id])
      });
      flash("\u2717 ".concat(ta, " \u2192 ").concat(tb, " can't connect \u2014 inserted Adapter"));
    }
  };
  var disconnectWire = function disconnectWire(a, b) {
    setM(function (m) {
      return _objectSpread(_objectSpread({}, m), {}, {
        wires: m.wires.filter(function (w) {
          return !(w.a === a && w.b === b) && !(w.a === b && w.b === a);
        })
      });
    });
    flash('Wire cut');
  };
  var disconnectAll = function disconnectAll(id) {
    setM(function (m) {
      return _objectSpread(_objectSpread({}, m), {}, {
        wires: m.wires.filter(function (w) {
          return w.a !== id && w.b !== id;
        })
      });
    });
    flash('Disconnected all wires');
  };
  var freezeNode = function freezeNode(id) {
    var n = M.nodes.find(function (x) {
      return x.id === id;
    });
    patchNode(id, {
      frozen: !(n && n.frozen)
    });
    flash(n && n.frozen ? 'Unfrozen' : 'Frozen — locked from edits & runs');
  };
  var duplicateNode = function duplicateNode(id) {
    var n = M.nodes.find(function (x) {
      return x.id === id;
    });
    if (!n) return;
    var nid = 'n_' + Date.now().toString(36);
    setM(function (m) {
      return _objectSpread(_objectSpread({}, m), {}, {
        nodes: [].concat(_toConsumableArray(m.nodes), [_objectSpread(_objectSpread({}, n), {}, {
          id: nid,
          frozen: false,
          rt: undefined,
          x: n.x + 28,
          y: n.y + 28,
          title: n.title + ' copy'
        })])
      });
    });
    setSel({
      domain: null,
      nodes: new Set([nid])
    });
    flash('Duplicated');
  };
  var onNodeContext = function onNodeContext(id, x, y) {
    if (!sel.nodes.has(id)) setSel({
      domain: null,
      nodes: new Set([id])
    });
    setCtx({
      type: 'node',
      id: id,
      x: x,
      y: y
    });
  };
  var onWireContext = function onWireContext(a, b, x, y, bundle) {
    return setCtx({
      type: 'wire',
      a: a,
      b: b,
      x: x,
      y: y,
      bundle: bundle
    });
  };
  var pickWire = function pickWire(w) {
    return setSel({
      domain: null,
      domains: new Set(),
      nodes: new Set(),
      fields: new Set(),
      field: null,
      wire: w
    });
  };
  // delete every underlying wire in a bundle — the visible line is a roll-up, so removing it
  // must remove what it stands for, not just the one wire that named it
  var deleteWireBundle = function deleteWireBundle(w) {
    if (!w) return;
    var domOfN = {};
    M.nodes.forEach(function (n) {
      return domOfN[n.id] = n.dom;
    });
    setM(function (m) {
      return _objectSpread(_objectSpread({}, m), {}, {
        wires: m.wires.filter(function (x) {
          var da = domOfN[x.a] || x.a,
            db = domOfN[x.b] || x.b;
          var sameBundle = da === w.da && db === w.db || da === w.db && db === w.da;
          var samePair = x.a === w.a && x.b === w.b || x.a === w.b && x.b === w.a;
          return w.cross ? !sameBundle : !samePair;
        })
      });
    });
    setSel(function (s) {
      return _objectSpread(_objectSpread({}, s), {}, {
        wire: null
      });
    });
    flash(w.cross ? "Removed ".concat(w.wt, " wire").concat(w.wt > 1 ? 's' : '') : 'Wire removed');
  };
  var bulkStatus = function bulkStatus(st) {
    var s = new Set(sel.nodes);
    setM(function (m) {
      return _objectSpread(_objectSpread({}, m), {}, {
        nodes: m.nodes.map(function (n) {
          return s.has(n.id) ? _objectSpread(_objectSpread({}, n), {}, {
            status: st
          }) : n;
        })
      });
    });
    flash("".concat(sel.nodes.size, " \u2192 ").concat(st));
  };
  var bulkDomain = function bulkDomain(dom) {
    var s = new Set(sel.nodes);
    setM(function (m) {
      return _objectSpread(_objectSpread({}, m), {}, {
        nodes: m.nodes.map(function (n) {
          return s.has(n.id) ? _objectSpread(_objectSpread({}, n), {}, {
            dom: dom
          }) : n;
        })
      });
    });
    flash("".concat(sel.nodes.size, " \u2192 ").concat(domName(dom)));
  };
  var bulkAgent = function bulkAgent(agentId) {
    setAssign(function (a) {
      var next = _objectSpread({}, a);
      sel.nodes.forEach(function (id) {
        return next[id] = _toConsumableArray(new Set([].concat(_toConsumableArray(next[id] || []), [agentId])));
      });
      return next;
    });
    flash("Assigned ".concat(sel.nodes.size, " nodes"));
  };
  var toggleAgent = function toggleAgent(nodeId, agentId) {
    return setAssign(function (a) {
      var cur = a[nodeId] || [];
      var on = cur.includes(agentId);
      var next = _objectSpread(_objectSpread({}, a), {}, _defineProperty({}, nodeId, on ? cur.filter(function (x) {
        return x !== agentId;
      }) : [].concat(_toConsumableArray(cur), [agentId])));
      // an agent arriving puts the node to work; the last one leaving stands it down
      if (!on) queueWork(nodeId, agentId);else if (next[nodeId].length === 0) standDown(nodeId);
      return next;
    });
  };

  // ── the agent work loop: assigned nodes actually run, and the run propagates ──
  var queueWork = function queueWork(nodeId, agentId) {
    setM(function (m) {
      return _objectSpread(_objectSpread({}, m), {}, {
        nodes: m.nodes.map(function (n) {
          return n.id === nodeId ? _objectSpread(_objectSpread({}, n), {}, {
            rt: _objectSpread(_objectSpread({}, n.rt || {}), {}, {
              state: 'running',
              by: agentId,
              since: Date.now(),
              runs: n.rt && n.rt.runs || []
            })
          }) : n;
        })
      });
    });
  };
  var standDown = function standDown(nodeId) {
    setM(function (m) {
      return _objectSpread(_objectSpread({}, m), {}, {
        nodes: m.nodes.map(function (n) {
          return n.id === nodeId ? _objectSpread(_objectSpread({}, n), {}, {
            rt: _objectSpread(_objectSpread({}, n.rt || {}), {}, {
              state: n.rt && n.rt.runs && n.rt.runs.length ? 'fresh' : 'idle',
              by: null
            })
          }) : n;
        })
      });
    });
  };
  var addNode = function addNode(domKey) {
    var key = domKey || sel.domain || (M.domains[0] || {}).key;
    var d = M.domains.find(function (x) {
      return x.key === key;
    }) || M.domains[0];
    var sibs = M.nodes.filter(function (n) {
      return n.dom === key;
    }).length;
    var id = 'n_' + Date.now().toString(36);
    var nx = d.x + 24 + sibs % 4 * 138,
      ny = d.y + 64 + Math.floor(sibs / 4) * 104;
    setM(function (m) {
      return _objectSpread(_objectSpread({}, m), {}, {
        nodes: [].concat(_toConsumableArray(m.nodes), [{
          id: id,
          dom: key,
          cat: 'custom',
          title: 'New capability',
          sub: 'describe its intent',
          status: 'vision',
          params: [],
          evidence_ref: '',
          x: nx,
          y: ny
        }])
      });
    });
    focusDomain(key);
    setSel({
      domain: null,
      nodes: new Set([id])
    });
    flash('Node created');
  };
  var createFromLibrary = function createFromLibrary(item, domKey, at) {
    var key = domKey || sel.domain || (M.domains[0] || {}).key;
    var d = M.domains.find(function (x) {
      return x.key === key;
    }) || M.domains[0];
    if (!d) return;
    var sibs = M.nodes.filter(function (n) {
      return n.dom === key;
    }).length;
    var id = 'n_' + Date.now().toString(36);
    var nx = at ? at.x : d.x + 24 + sibs % 4 * 178,
      ny = at ? at.y : d.y + 64 + Math.floor(sibs / 4) * 112;
    setM(function (m) {
      return _objectSpread(_objectSpread({}, m), {}, {
        nodes: [].concat(_toConsumableArray(m.nodes), [{
          id: id,
          dom: key,
          cat: item.cat,
          title: item.title,
          sub: item.sub,
          status: 'vision',
          params: [],
          evidence_ref: '',
          x: nx,
          y: ny
        }])
      });
    });
    focusDomain(key);
    setSel({
      domain: null,
      domains: new Set(),
      nodes: new Set([id]),
      field: null
    });
    flash("".concat(item.title, " \u2192 ").concat(d.title));
  };
  var addDomain = function addDomain(title, col) {
    var key = (title || 'domain').toLowerCase().replace(/[^a-z0-9]+/g, '_').slice(0, 14) + '_' + Math.random().toString(36).slice(2, 4);
    var cols = M.domains.length;
    var x = 40 + cols % 4 * 600,
      y = 40 + Math.floor(cols / 4) * 572;
    setM(function (m) {
      return _objectSpread(_objectSpread({}, m), {}, {
        domains: [].concat(_toConsumableArray(m.domains), [{
          key: key,
          title: title || 'New Domain',
          col: col || DOM_COLS[cols % DOM_COLS.length],
          x: x,
          y: y,
          w: 568,
          h: 540
        }])
      });
    });
    setVis(function (v) {
      return _objectSpread(_objectSpread({}, v), {}, {
        domains: new Set([].concat(_toConsumableArray(v.domains), [key]))
      });
    });
    flash("Domain \"".concat(title, "\" created"));
  };
  // ── RECURSION: group selected nodes INTO a new grand node (a container domain).
  // Reuses the proven super-node machinery — it collapses to a volume, opens to its
  // members, grows interface knobs, edge-routes its wires. Grand nodes can be grouped
  // again one tier up (→ a field, the top of the ladder). og remembers each node's prior home. ──
  var groupSelection = function groupSelection() {
    var ids = _toConsumableArray(sel.nodes);
    if (ids.length < 2) {
      flash('Select 2 or more things to group');
      return;
    }
    var ns = M.nodes.filter(function (n) {
      return ids.includes(n.id);
    });
    var key = 'grp_' + Date.now().toString(36);
    var cx = Math.round(ns.reduce(function (a, n) {
      return a + n.x;
    }, 0) / ns.length);
    var cy = Math.round(ns.reduce(function (a, n) {
      return a + n.y;
    }, 0) / ns.length);
    setM(function (m) {
      return _objectSpread(_objectSpread({}, m), {}, {
        domains: [].concat(_toConsumableArray(m.domains), [function () {
          var p = freeCell(m, cx - 30, cy - 50);
          return {
            key: key,
            title: deriveGroupName(ns.map(function (x) {
              return x.title;
            })),
            col: HB.accent,
            x: p.x,
            y: p.y,
            w: (m.grid || {
              dw: 560
            }).dw || 560,
            h: (m.grid || {
              dh: 480
            }).dh || 480,
            grouped: true
          };
        }()]),
        nodes: m.nodes.map(function (n) {
          return ids.includes(n.id) ? _objectSpread(_objectSpread({}, n), {}, {
            og: n.og != null ? n.og : n.dom,
            dom: key
          }) : n;
        })
      });
    });
    setVis(function (v) {
      return _objectSpread(_objectSpread({}, v), {}, {
        domains: new Set([].concat(_toConsumableArray(v.domains), [key]))
      });
    });
    setExpanded(function (e) {
      return {
        open: new Set([].concat(_toConsumableArray(e.open), [key])),
        collapsed: e.collapsed
      };
    });
    setSel({
      domain: key,
      domains: new Set([key]),
      nodes: new Set(),
      fields: new Set(),
      field: null,
      wire: null
    });
    flash("Grouped ".concat(ids.length, " \u2192 one node"));
    setTimeout(function () {
      return canvas.current && canvas.current.focusDomain(key);
    }, 70);
  };
  // ── one tier up: group selected domains (and any loose nodes) INTO a field. ──
  // A field is just another node on the graph; loose nodes are first wrapped into a
  // grand node so the field is uniformly made of grand nodes. ──
  var fieldOf = function fieldOf(key) {
    return (M.fields || []).find(function (f) {
      return (f.domKeys || []).includes(key);
    });
  };
  var fieldById = function fieldById(id) {
    return (M.fields || []).find(function (f) {
      return f.id === id;
    });
  };
  // a field's own parent field (if it has been grouped again one tier up)
  var parentField = function parentField(id) {
    return (M.fields || []).find(function (f) {
      return (f.fieldIds || []).includes(id);
    });
  };
  // how many tiers of grouping sit BELOW a field — 1 = holds domains only, 2 = holds a
  // field that holds domains, and so on. This is what makes the ladder unbounded.
  var _fieldDepth = function fieldDepth(id, seen) {
    var f = fieldById(id);
    if (!f) return 0;
    var guard = seen || new Set();
    if (guard.has(id)) return 0;
    guard.add(id);
    var kids = (f.fieldIds || []).map(function (k) {
      return _fieldDepth(k, guard);
    });
    return 1 + (kids.length ? Math.max.apply(Math, _toConsumableArray(kids)) : 0);
  };
  // every domain reachable from a field, at any depth
  var _fieldDomains = function fieldDomains(id, seen) {
    var f = fieldById(id);
    if (!f) return [];
    var guard = seen || new Set();
    if (guard.has(id)) return [];
    guard.add(id);
    return [].concat(_toConsumableArray(f.domKeys || []), _toConsumableArray((f.fieldIds || []).flatMap(function (k) {
      return _fieldDomains(k, guard);
    })));
  };
  // deepest grouping tier present anywhere in the model — drives the scale ladder
  var modelDepth = (M.fields || []).reduce(function (mx, f) {
    return Math.max(mx, _fieldDepth(f.id));
  }, 0);
  var groupIntoField = function groupIntoField() {
    var domKeys = _toConsumableArray(sel.domains || new Set());
    var looseIds = _toConsumableArray(sel.nodes);
    // a selected field is a legitimate member of a bigger field — this is the recursion
    var childFields = _toConsumableArray(sel.fields || new Set()).filter(function (id) {
      return !parentField(id);
    });
    var memberCount = domKeys.length + childFields.length + (looseIds.length ? 1 : 0);
    if (memberCount < 2) {
      flash('Select 2 or more things to group');
      return;
    }
    var fid = 'fld_' + Date.now().toString(36);
    var gk = looseIds.length ? 'grp_' + Date.now().toString(36) : null;
    var allKeys = gk ? [].concat(_toConsumableArray(domKeys), [gk]) : domKeys;
    setM(function (m) {
      var domains = m.domains,
        nodes = m.nodes;
      if (gk) {
        var ns = m.nodes.filter(function (n) {
          return looseIds.includes(n.id);
        });
        var cx = Math.round(ns.reduce(function (a, n) {
            return a + n.x;
          }, 0) / ns.length),
          cy = Math.round(ns.reduce(function (a, n) {
            return a + n.y;
          }, 0) / ns.length);
        var gp = freeCell(m, cx - 30, cy - 50);
        domains = [].concat(_toConsumableArray(domains), [{
          key: gk,
          title: deriveGroupName(ns.map(function (x) {
            return x.title;
          })),
          col: HB.accent,
          x: gp.x,
          y: gp.y,
          w: (m.grid || {
            dw: 560
          }).dw || 560,
          h: (m.grid || {
            dh: 480
          }).dh || 480,
          grouped: true
        }]);
        nodes = m.nodes.map(function (n) {
          return looseIds.includes(n.id) ? _objectSpread(_objectSpread({}, n), {}, {
            og: n.og != null ? n.og : n.dom,
            dom: gk
          }) : n;
        });
      }
      var tier = childFields.length ? 1 + Math.max.apply(Math, _toConsumableArray(childFields.map(function (k) {
        return _fieldDepth(k);
      }))) : 1;
      var memberTitles = [].concat(_toConsumableArray(domKeys.map(function (k) {
        return (m.domains.find(function (d) {
          return d.key === k;
        }) || {}).title;
      }).filter(Boolean)), _toConsumableArray(childFields.map(function (k) {
        return (m.fields || []).find(function (f) {
          return f.id === k;
        });
      }).filter(Boolean).map(function (f) {
        return f.title;
      })));
      var title = deriveGroupName(memberTitles);
      return _objectSpread(_objectSpread({}, m), {}, {
        domains: domains,
        nodes: nodes,
        fields: [].concat(_toConsumableArray(m.fields || []), [{
          id: fid,
          title: title,
          col: tier > 1 ? HB.purple : HB.blue,
          domKeys: allKeys,
          fieldIds: childFields
        }])
      });
    });
    if (gk) {
      setVis(function (v) {
        return _objectSpread(_objectSpread({}, v), {}, {
          domains: new Set([].concat(_toConsumableArray(v.domains), [gk]))
        });
      });
      setExpanded(function (e) {
        return {
          open: new Set([].concat(_toConsumableArray(e.open), [gk])),
          collapsed: e.collapsed
        };
      });
    }
    setSel({
      domain: null,
      domains: new Set(),
      nodes: new Set(),
      fields: new Set(),
      field: fid
    });
    flash("Grouped ".concat(memberCount, " \u2192 one node"));
  };
  var _ungroupField = function ungroupField(id) {
    // release children rather than orphaning them: they stay as their own fields one tier down
    setM(function (m) {
      return _objectSpread(_objectSpread({}, m), {}, {
        fields: (m.fields || []).filter(function (f) {
          return f.id !== id;
        }).map(function (f) {
          return (f.fieldIds || []).includes(id) ? _objectSpread(_objectSpread({}, f), {}, {
            fieldIds: f.fieldIds.filter(function (k) {
              return k !== id;
            })
          }) : f;
        })
      });
    });
    setSel(function (s) {
      return s.field === id ? {
        domain: null,
        domains: new Set(),
        nodes: new Set(),
        fields: new Set(),
        field: null,
        wire: null
      } : s;
    });
    flash('Field ungrouped — domains remain');
  };
  var patchField = function patchField(id, patch) {
    return setM(function (m) {
      return _objectSpread(_objectSpread({}, m), {}, {
        fields: (m.fields || []).map(function (f) {
          return f.id === id ? _objectSpread(_objectSpread({}, f), patch) : f;
        })
      });
    });
  };
  // group dispatcher — picks the right tier from what's selected (everything is a node)
  var groupAny = function groupAny() {
    if ((sel.fields || new Set()).size >= 1 || (sel.domains || new Set()).size >= 1) groupIntoField();else groupSelection();
  };
  var onDomainContext = function onDomainContext(key, x, y) {
    setSel(function (s) {
      return s.domains && s.domains.has(key) ? s : {
        domain: key,
        domains: new Set([key]),
        nodes: new Set(),
        fields: new Set(),
        field: null,
        wire: null
      };
    });
    setCtx({
      type: 'domain',
      key: key,
      x: x,
      y: y
    });
  };
  var onFieldContext = function onFieldContext(id, x, y) {
    setSel({
      domain: null,
      domains: new Set(),
      nodes: new Set(),
      field: id
    });
    setCtx({
      type: 'field',
      id: id,
      x: x,
      y: y
    });
  };
  var ungroupDomain = function ungroupDomain(key) {
    var d = M.domains.find(function (x) {
      return x.key === key;
    });
    if (!d || !d.grouped) return;
    setM(function (m) {
      var fallback = (m.domains.find(function (z) {
        return z.key !== key;
      }) || {}).key;
      return _objectSpread(_objectSpread({}, m), {}, {
        domains: m.domains.filter(function (x) {
          return x.key !== key;
        }),
        nodes: m.nodes.map(function (n) {
          return n.dom === key ? _objectSpread(_objectSpread({}, n), {}, {
            dom: n.og || fallback,
            og: undefined
          }) : n;
        })
      });
    });
    setVis(function (v) {
      var nd = new Set(v.domains);
      nd["delete"](key);
      return _objectSpread(_objectSpread({}, v), {}, {
        domains: nd
      });
    });
    setSel({
      domain: null,
      domains: new Set(),
      nodes: new Set(),
      fields: new Set(),
      field: null,
      wire: null
    });
    flash('Ungrouped — nodes returned home');
  };
  // ── scale ladder: which rung of the recursive primitive is currently resolved ──
  var scaleLevel = openNodes.size ? 'stage' : expanded.open.size ? 'node' : expanded.collapsed.size === M.domains.length ? 'domain' : 'field';
  var climbTo = function climbTo(k) {
    if (k === 'stage') {
      var id = _toConsumableArray(sel.nodes)[0];
      if (id) {
        toggleNode(id, !openNodes.has(id));
        flash('Cells — the node resolved into its parameters');
      } else flash('Select a node, then climb to CELL to open its parameters');
    } else if (k === 'node') {
      expandAll();
      flash('Resolved to nodes — the building block');
    } else if (k === 'domain') {
      collapseAll();
      flash('Domains — each a grand node of its nodes');
    } else if (k === 'field') {
      collapseAll();
      setTimeout(fitAll, 40);
      flash('The field — every domain at once');
    } else if (k.startsWith('field')) {
      var tier = +k.slice(5);
      var f = (M.fields || []).find(function (x) {
        return _fieldDepth(x.id) === tier;
      });
      collapseAll();
      setTimeout(fitAll, 40);
      flash(f ? "Tier ".concat(tier, " \u2014 ").concat(f.title) : "Tier ".concat(tier));
    }
  };
  // ── agents AS NODES: drop an agent onto a domain and wire it to that domain's nodes ──
  var addAgentNode = function addAgentNode(agentId) {
    var ag = DB.agents.find(function (a) {
      return a.id === agentId;
    });
    if (!ag) return;
    var key = sel.domain || (sel.nodes.size === 1 ? (M.nodes.find(function (n) {
      return sel.nodes.has(n.id);
    }) || {}).dom : null) || (M.domains[0] || {}).key;
    var d = M.domains.find(function (x) {
      return x.key === key;
    }) || M.domains[0];
    var id = 'agn_' + agentId + '_' + Date.now().toString(36);
    var sibs = M.nodes.filter(function (n) {
      return n.dom === key;
    });
    var nx = d.x + 24,
      ny = d.y + 64 + sibs.length % 3 * 100;
    // wire the agent node to up to 4 of the domain's nodes (it operates them)
    var targets = sibs.slice(0, 4);
    var newWires = targets.map(function (t) {
      return {
        a: id,
        b: t.id,
        why: "".concat(ag.name, " operates this"),
        kind: 'owns'
      };
    });
    setM(function (m) {
      return _objectSpread(_objectSpread({}, m), {}, {
        nodes: [].concat(_toConsumableArray(m.nodes), [{
          id: id,
          dom: key,
          cat: 'agent',
          agentId: agentId,
          title: ag.name,
          sub: ag.model ? (DB.models.find(function (mm) {
            return mm.id === ag.model;
          }) || {}).name || 'agent' : 'agent',
          status: 'live',
          params: [{
            k: 'autonomy',
            v: ag.autonomy || 'propose'
          }],
          evidence_ref: '',
          x: nx,
          y: ny
        }]),
        wires: [].concat(_toConsumableArray(m.wires), _toConsumableArray(newWires))
      });
    });
    focusDomain(key);
    setSel({
      domain: null,
      nodes: new Set([id])
    });
    flash("".concat(ag.name, " attached \u2192 ").concat(d.title));
  };

  // ── connective-tissue nodes: the SAME stem grammar as the app session canvas ──
  var addConnective = function addConnective(spec) {
    var key = sel.domain || (sel.nodes.size === 1 ? (M.nodes.find(function (n) {
      return sel.nodes.has(n.id);
    }) || {}).dom : null) || (M.domains[0] || {}).key;
    var d = M.domains.find(function (x) {
      return x.key === key;
    }) || M.domains[0];
    var sibs = M.nodes.filter(function (n) {
      return n.dom === key;
    }).length;
    var id = spec.kind + '_' + Date.now().toString(36);
    var nx = d.x + 24 + sibs % 4 * 138,
      ny = d.y + 64 + Math.floor(sibs / 4) * 104;
    setM(function (m) {
      return _objectSpread(_objectSpread({}, m), {}, {
        nodes: [].concat(_toConsumableArray(m.nodes), [{
          id: id,
          dom: key,
          cat: spec.cat,
          title: spec.title,
          sub: spec.sub,
          status: 'live',
          params: (spec.params || []).map(function (p) {
            return _objectSpread({}, p);
          }),
          evidence_ref: '',
          x: nx,
          y: ny
        }])
      });
    });
    focusDomain(key);
    setSel({
      domain: null,
      nodes: new Set([id])
    });
    flash("".concat(spec.title, " dropped \u2192 ").concat(d.title));
  };

  // ── visibility ──
  var toggleVisDomain = function toggleVisDomain(k) {
    return setVis(function (v) {
      var n = new Set(v.domains);
      n.has(k) ? n["delete"](k) : n.add(k);
      return _objectSpread(_objectSpread({}, v), {}, {
        domains: n
      });
    });
  };
  var toggleVisStatus = function toggleVisStatus(k) {
    return setVis(function (v) {
      var n = new Set(v.status);
      n.has(k) ? n["delete"](k) : n.add(k);
      return _objectSpread(_objectSpread({}, v), {}, {
        status: n
      });
    });
  };
  var allDomains = function allDomains() {
    return setVis(function (v) {
      return _objectSpread(_objectSpread({}, v), {}, {
        domains: new Set(M.domains.map(function (d) {
          return d.key;
        }))
      });
    });
  };
  var openRoom = function openRoom() {};

  // ── command bar ──
  var runCmd = function runCmd() {
    var c = cmd.trim();
    if (!c) return;
    setCmd('');
    var lc = c.toLowerCase();
    var domHit = M.domains.find(function (d) {
      return lc.includes(d.key) || lc.includes(d.title.toLowerCase().split(' ')[0]);
    });
    var stHit = STATUS_ORDER.find(function (s) {
      return lc.includes(s);
    });
    if (/(enter|open|focus|fly|go|operate|room|control)/.test(lc) && domHit) {
      focusDomain(domHit.key);
      pickDomain(domHit.key);
      flash("Opened ".concat(domHit.title));
    } else if (/(expand all|open all)/.test(lc)) {
      expandAll();
      flash('All domains expanded');
    } else if (/(collapse all|close all)/.test(lc)) {
      collapseAll();
      flash('All domains collapsed');
    } else if (/(fit|whole|overview|macro|home|out)/.test(lc)) {
      collapseAll();
      setTimeout(fitAll, 40);
      flash('Whole model');
    } else if (/select/.test(lc) && stHit) {
      selectBy(function (n) {
        return n.status === stHit;
      });
      flash("Selected ".concat(counts[stHit], " ").concat(stHit));
    } else if (/select/.test(lc) && domHit) {
      selectBy(function (n) {
        return n.dom === domHit.key;
      });
      flash("Selected ".concat(domHit.title));
    } else if (/(health|status|where|progress)/.test(lc)) {
      flash("".concat(counts.live, " live \xB7 ").concat(counts.partial, " partial \xB7 ").concat(counts.vision, " vision \xB7 ").concat(total, " nodes / ").concat(M.domains.length, " domains"));
    } else if (domHit) {
      focusDomain(domHit.key);
      flash(domHit.title);
    } else flash('Try: "open brain", "operate models", "expand all", "fit", "health".');
  };

  // ── attention layer: what matters now ──
  var gotoAttention = function gotoAttention(it) {
    if (it.nodeId) inspectNode(it.nodeId);else {
      focusDomain(it.dom);
      pickDomain(it.dom);
    }
  };
  var tuneAttention = function tuneAttention() {
    var a = M.nodes.find(function (n) {
      return n.cat === 'attention';
    });
    if (a) inspectNode(a.id);
  };

  // ── INSPECT panel (left, selection-aware) ──
  var inspectPanel;
  var multiDom = (sel.domains || new Set()).size > 1 || (sel.domains || new Set()).size >= 1 && sel.nodes.size >= 1;
  var selFieldSet = sel.fields || new Set();
  if (sel.wire) inspectPanel = /*#__PURE__*/React.createElement(WirePanel, {
    M: M,
    w: sel.wire,
    onDelete: function onDelete() {
      return deleteWireBundle(sel.wire);
    },
    onGoto: function onGoto(id) {
      var n = M.nodes.find(function (x) {
        return x.id === id;
      });
      if (n) {
        focusDomain(n.dom);
        pickNode(id, false);
      }
    },
    onClose: clearSel
  });else if (selFieldSet.size > 1) inspectPanel = /*#__PURE__*/React.createElement(MultiFieldPanel, {
    M: M,
    ids: _toConsumableArray(selFieldSet),
    onGroup: groupIntoField,
    clearSel: clearSel
  });else if (sel.field) inspectPanel = /*#__PURE__*/React.createElement(FieldPanel, {
    M: M,
    fieldId: sel.field,
    patchField: patchField,
    onUngroup: _ungroupField,
    onEnterDomain: function onEnterDomain(k) {
      focusDomain(k);
      pickDomain(k);
    },
    onClose: clearSel
  });else if (multiDom) inspectPanel = /*#__PURE__*/React.createElement(MultiPanel, {
    selDomains: _toConsumableArray(sel.domains || new Set()),
    selNodes: sel.nodes,
    M: M,
    onGroupField: groupIntoField,
    clearSel: clearSel
  });else if (sel.nodes.size > 1) inspectPanel = /*#__PURE__*/React.createElement(BulkPanel, {
    sel: sel.nodes,
    selNodes: selNodes,
    M: M,
    DB: DB,
    STATUS: STATUS_ORDER,
    bulkStatus: bulkStatus,
    bulkDomain: bulkDomain,
    bulkAgent: bulkAgent,
    onGroup: groupSelection,
    onDelete: function onDelete() {
      return delNodes(_toConsumableArray(sel.nodes));
    },
    clearSel: clearSel,
    domName: domName
  });else if (sel.nodes.size === 1) {
    var node = M.nodes.find(function (n) {
      return n.id === _toConsumableArray(sel.nodes)[0];
    });
    inspectPanel = /*#__PURE__*/React.createElement(NodeInspector, {
      key: node.id,
      M: M,
      node: node,
      DB: DB,
      assign: assign,
      STATUS: STATUS_ORDER,
      CATS: CAT_LIST,
      patchNode: patchNode,
      delNode: function delNode(id) {
        return delNodes([id]);
      },
      toggleAgent: toggleAgent,
      onClose: clearSel,
      openRoom: openRoom,
      focusNode: function focusNode(id) {
        return inspectNode(id);
      },
      domName: domName,
      onRun: runNode,
      onVariant: runVariant,
      onWatch: addWatcher
    });
  } else if (sel.domain) inspectPanel = /*#__PURE__*/React.createElement(DomainPanel, {
    M: M,
    domKey: sel.domain,
    DB: DB,
    counts: counts,
    STATUS: STATUS_ORDER,
    CATS: CAT_LIST,
    patchDomain: patchDomain,
    assign: assign,
    toggleAgent: toggleAgent,
    onEnter: function onEnter() {
      return focusDomain(sel.domain);
    },
    onAddNode: function onAddNode() {
      return addNode(sel.domain);
    },
    onUngroup: ungroupDomain,
    openRoom: openRoom,
    selectBy: selectBy,
    onClose: clearSel
  });else inspectPanel = /*#__PURE__*/React.createElement(SystemPanel, {
    M: M,
    counts: counts,
    total: total,
    STATUS: STATUS_ORDER,
    attention: [],
    onGoto: gotoAttention,
    onAddDomain: function onAddDomain() {
      return setDomModal(true);
    },
    onEnter: function onEnter(k) {
      focusDomain(k);
      pickDomain(k);
    },
    openRoom: openRoom
  });
  var railW = 316,
    rightW = 316; // equal rails — the map sits centred between them
  var allExpanded = expanded.open.size === M.domains.length && expanded.collapsed.size === 0;
  var allCollapsed = expanded.collapsed.size === M.domains.length;
  return /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'fixed',
      inset: 0,
      background: HB.paper,
      color: HB.ink,
      fontFamily: HB.sans,
      overflow: 'hidden',
      display: 'flex',
      flexDirection: 'column'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      height: 52,
      flexShrink: 0,
      display: 'flex',
      alignItems: 'center',
      gap: 14,
      padding: '0 16px',
      borderBottom: "1px solid ".concat(HB.line),
      background: HB.card,
      zIndex: 10
    }
  }, /*#__PURE__*/React.createElement("svg", {
    width: "22",
    height: "22",
    viewBox: "0 0 64 64",
    fill: "none"
  }, /*#__PURE__*/React.createElement("path", {
    d: "M10 56 V32 a22 22 0 0 1 44 0 V56",
    stroke: HB.accent,
    strokeWidth: "4.5",
    strokeLinecap: "square"
  }), /*#__PURE__*/React.createElement("circle", {
    cx: "32",
    cy: "22",
    r: "5.2",
    fill: HB.card,
    stroke: HB.accent,
    strokeWidth: "2.4"
  }), /*#__PURE__*/React.createElement("circle", {
    cx: "32",
    cy: "22",
    r: "1.8",
    fill: HB.accent
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      flexShrink: 0
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: HB.arch,
      fontSize: 15,
      textTransform: 'uppercase',
      letterSpacing: '0.02em',
      lineHeight: '22px',
      whiteSpace: 'nowrap'
    }
  }, "Arch", /*#__PURE__*/React.createElement("span", {
    style: {
      color: HB.accent
    }
  }, "Hub"), " ", /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: HB.serif,
      textTransform: 'none',
      fontSize: 14,
      color: HB.inkSoft
    }
  }, "\xB7 Founder Cockpit")), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: HB.mono,
      fontSize: 7.5,
      color: HB.inkMute,
      letterSpacing: '0.2em',
      lineHeight: 1.4
    }
  }, "THE GRAND MAP")), /*#__PURE__*/React.createElement("div", {
    style: {
      marginLeft: 14,
      display: 'flex',
      alignItems: 'center',
      gap: 10
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width: 200,
      height: 8,
      borderRadius: 4,
      overflow: 'hidden',
      display: 'flex',
      border: "1px solid ".concat(HB.line)
    }
  }, STATUS_ORDER.filter(function (s) {
    return counts[s];
  }).map(function (s) {
    return /*#__PURE__*/React.createElement("span", {
      key: s,
      title: "".concat(s, ": ").concat(counts[s]),
      style: {
        width: "".concat(counts[s] / total * 100, "%"),
        background: STC[s]
      }
    });
  })), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: HB.mono,
      fontSize: 10.5,
      color: HB.inkSoft
    }
  }, /*#__PURE__*/React.createElement("b", {
    style: {
      color: HB.green
    }
  }, counts.live), "L \xB7 ", /*#__PURE__*/React.createElement("b", {
    style: {
      color: HB.amber
    }
  }, counts.partial), "P \xB7 ", /*#__PURE__*/React.createElement("b", {
    style: {
      color: HB.accent
    }
  }, counts.vision), "V")), /*#__PURE__*/React.createElement("div", {
    style: {
      marginLeft: 'auto',
      display: 'flex',
      alignItems: 'stretch',
      border: "1px solid ".concat(HB.line),
      borderRadius: 6,
      overflow: 'hidden',
      fontFamily: HB.mono
    }
  }, [['NODES', total], ['DOMAINS', M.domains.length], ['WIRES', M.wires.length], ['SHEET', 'GA-01'], ['DRAWN', 'FOUNDER']].map(function (_ref10, i) {
    var _ref11 = _slicedToArray(_ref10, 2),
      k = _ref11[0],
      v = _ref11[1];
    return /*#__PURE__*/React.createElement("div", {
      key: k,
      style: {
        padding: '4px 11px',
        borderLeft: i ? "1px solid ".concat(HB.line) : 'none',
        textAlign: 'center'
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 7,
        color: HB.inkMute,
        letterSpacing: '0.1em'
      }
    }, k), /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 11,
        color: HB.ink,
        marginTop: 1
      }
    }, v));
  })), /*#__PURE__*/React.createElement("button", {
    onClick: function onClick() {
      return setLeftTab('inspect');
    },
    title: "Inspect",
    style: {
      display: 'none'
    }
  }), /*#__PURE__*/React.createElement(HAvatar, {
    name: "Mehdi Habib",
    size: 28
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      display: 'flex',
      minHeight: 0
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width: railW,
      flexShrink: 1,
      minWidth: 216,
      borderRight: "1px solid ".concat(HB.line),
      background: HB.card,
      display: 'grid',
      gridTemplateColumns: '44px 1fr',
      overflow: 'hidden',
      minHeight: 0
    }
  }, /*#__PURE__*/React.createElement(AtlasIconRail, {
    panel: leftTab,
    setPanel: setLeftTab,
    onFrameAll: fitAll,
    onTidy: autoOrganize
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      minHeight: 0,
      overflow: 'hidden'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      padding: '12px 14px 10px',
      borderBottom: "1px solid ".concat(HB.line),
      flexShrink: 0
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: HB.mono,
      fontSize: 10.5,
      letterSpacing: '0.08em',
      color: HB.ink
    }
  }, {
    library: 'LIBRARY',
    agents: 'AGENTS',
    index: 'INDEX',
    view: 'VIEW'
  }[leftTab])), /*#__PURE__*/React.createElement("div", {
    className: "hb-scroll",
    style: {
      flex: 1,
      overflowY: 'auto',
      overflowX: 'hidden',
      minHeight: 0
    }
  }, leftTab === 'library' && /*#__PURE__*/React.createElement(LibraryPanel, {
    onCreateNode: createFromLibrary,
    onAddDomain: function onAddDomain() {
      return setDomModal(true);
    },
    flash: flash
  }), leftTab === 'agents' && /*#__PURE__*/React.createElement(AgenticPanel, {
    M: M,
    DB: DB,
    assign: assign,
    attention: attention,
    onGoto: gotoAttention,
    onTuneAttention: tuneAttention,
    setColl: setColl,
    flash: flash
  }), leftTab === 'view' && /*#__PURE__*/React.createElement("div", {
    style: {
      padding: '12px 11px'
    }
  }, /*#__PURE__*/React.createElement(PanelLabel, null, "DETAIL"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      background: HB.paper2,
      borderRadius: 8,
      padding: 3,
      gap: 3
    }
  }, /*#__PURE__*/React.createElement("button", {
    onClick: collapseAll,
    title: "Show every domain as a single volume",
    style: segBtn(allCollapsed)
  }, "\u25FB Volumes"), /*#__PURE__*/React.createElement("button", {
    onClick: expandAll,
    title: "Resolve every domain into its nodes",
    style: segBtn(allExpanded)
  }, "\u229E Nodes")), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: HB.mono,
      fontSize: 9,
      color: HB.inkMute,
      padding: '5px 4px 0',
      lineHeight: 1.4
    }
  }, allExpanded ? 'all domains open to their nodes' : allCollapsed ? 'all domains shown as volumes' : 'mixed — zoom in to resolve more'), /*#__PURE__*/React.createElement(PanelLabel, null, "VIEW"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 6
    }
  }, /*#__PURE__*/React.createElement(MiniBtn, {
    onClick: function onClick() {
      collapseAll();
      setTimeout(fitAll, 40);
    },
    icon: "search"
  }, "Frame all"), /*#__PURE__*/React.createElement(MiniBtn, {
    onClick: autoOrganize,
    icon: "grid"
  }, "Tidy up")), /*#__PURE__*/React.createElement("button", {
    onClick: function onClick() {
      return setSelMode(function (s) {
        return !s;
      });
    },
    title: "Drag a box on the map to select many at once \u2014 collapsed domains, or nodes inside open domains \u2014 then Group",
    style: {
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      gap: 7,
      width: '100%',
      marginTop: 6,
      padding: '8px 0',
      borderRadius: 7,
      cursor: 'pointer',
      fontFamily: HB.mono,
      fontSize: 10.5,
      border: "1px solid ".concat(selMode ? HB.accent : HB.line),
      background: selMode ? HB.accentSoft : HB.card,
      color: selMode ? HB.accentHi : HB.inkSoft
    }
  }, /*#__PURE__*/React.createElement(CKIcon, {
    name: "grid",
    size: 12
  }), selMode ? 'Multi-select: ON — drag a box' : 'Multi-select (box)'), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: HB.mono,
      fontSize: 9,
      color: HB.inkMute,
      padding: '5px 4px 0',
      lineHeight: 1.45
    }
  }, "Drag a box to grab many \xB7 or ", /*#__PURE__*/React.createElement("b", {
    style: {
      color: HB.inkSoft
    }
  }, "\u21E7-click"), " domains / nodes to add \xB7 then ", /*#__PURE__*/React.createElement("b", {
    style: {
      color: HB.inkSoft
    }
  }, "Group")), /*#__PURE__*/React.createElement(PanelLabel, null, "LAYERS"), [['wires', 'Wires'], ['params', 'Parameters'], ['labels', 'Category labels']].map(function (_ref12) {
    var _ref13 = _slicedToArray(_ref12, 2),
      k = _ref13[0],
      l = _ref13[1];
    return /*#__PURE__*/React.createElement(ToggleRow, {
      key: k,
      label: l,
      on: vis[k],
      onClick: function onClick() {
        return setVis(function (v) {
          return _objectSpread(_objectSpread({}, v), {}, _defineProperty({}, k, !v[k]));
        });
      }
    });
  }), /*#__PURE__*/React.createElement(PanelLabel, {
    right: /*#__PURE__*/React.createElement("button", {
      onClick: function onClick() {
        return setVis(function (v) {
          return _objectSpread(_objectSpread({}, v), {}, {
            status: new Set(STATUS_ORDER)
          });
        });
      },
      style: miniLink
    }, "all")
  }, "STATUS \xB7 SHOW"), STATUS_ORDER.filter(function (s) {
    return counts[s];
  }).map(function (s) {
    return /*#__PURE__*/React.createElement("button", {
      key: s,
      onClick: function onClick() {
        return toggleVisStatus(s);
      },
      style: visRow(vis.status.has(s))
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        width: 9,
        height: 9,
        borderRadius: 2,
        background: STC[s],
        opacity: vis.status.has(s) ? 1 : 0.3
      }
    }), /*#__PURE__*/React.createElement("span", {
      style: {
        textTransform: 'capitalize',
        flex: 1
      }
    }, s), /*#__PURE__*/React.createElement("span", {
      style: {
        fontFamily: HB.mono,
        fontSize: 10,
        color: HB.inkMute
      }
    }, counts[s]), /*#__PURE__*/React.createElement(CKIcon, {
      name: vis.status.has(s) ? 'eye' : 'x',
      size: 12
    }));
  })), leftTab === 'index' && /*#__PURE__*/React.createElement("div", {
    style: {
      padding: '12px 11px'
    }
  }, /*#__PURE__*/React.createElement(PanelLabel, {
    right: /*#__PURE__*/React.createElement("button", {
      onClick: allDomains,
      style: miniLink
    }, "all")
  }, "DOMAINS \xB7 ", M.domains.length), M.domains.map(function (d) {
    var n = M.nodes.filter(function (x) {
      return x.dom === d.key;
    }).length;
    var on = vis.domains.has(d.key);
    return /*#__PURE__*/React.createElement("div", {
      key: d.key,
      style: visRow(on)
    }, /*#__PURE__*/React.createElement("span", {
      onClick: function onClick() {
        return toggleVisDomain(d.key);
      },
      style: {
        width: 9,
        height: 9,
        borderRadius: '50%',
        background: d.col,
        opacity: on ? 1 : 0.3,
        cursor: 'pointer',
        flexShrink: 0
      }
    }), /*#__PURE__*/React.createElement("span", {
      onClick: function onClick() {
        return focusDomain(d.key);
      },
      title: "Open + zoom",
      style: {
        flex: 1,
        overflow: 'hidden',
        textOverflow: 'ellipsis',
        whiteSpace: 'nowrap',
        cursor: 'pointer',
        color: expanded.open.has(d.key) ? HB.accent : 'inherit'
      }
    }, d.title), /*#__PURE__*/React.createElement("span", {
      style: {
        fontFamily: HB.mono,
        fontSize: 10,
        color: HB.inkMute
      }
    }, n), /*#__PURE__*/React.createElement("span", {
      onClick: function onClick() {
        return toggleVisDomain(d.key);
      },
      style: {
        cursor: 'pointer',
        display: 'grid',
        placeItems: 'center'
      }
    }, /*#__PURE__*/React.createElement(CKIcon, {
      name: on ? 'eye' : 'x',
      size: 12
    })));
  }), /*#__PURE__*/React.createElement(PanelLabel, null, "STEM \xB7 DROP NODES"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: HB.mono,
      fontSize: 9,
      color: HB.inkMute,
      padding: '0 4px 6px',
      lineHeight: 1.4
    }
  }, "same grammar as the app canvas \u2014 wire them, type-check, translate"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'grid',
      gridTemplateColumns: '1fr 1fr',
      gap: 6,
      padding: '0 4px'
    }
  }, STEM_KINDS.map(function (s) {
    return /*#__PURE__*/React.createElement("button", {
      key: s.kind,
      onClick: function onClick() {
        return addConnective(s);
      },
      title: s.sub,
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        textAlign: 'left',
        padding: '7px 9px',
        borderRadius: 7,
        border: "1px solid ".concat(HB.line),
        background: HB.paper2,
        cursor: 'pointer',
        color: HB.ink
      },
      onMouseEnter: function onMouseEnter(e) {
        e.currentTarget.style.borderColor = catCol(s.cat);
        e.currentTarget.style.background = HB.card;
      },
      onMouseLeave: function onMouseLeave(e) {
        e.currentTarget.style.borderColor = HB.line;
        e.currentTarget.style.background = HB.paper2;
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        width: 18,
        height: 18,
        borderRadius: 5,
        display: 'grid',
        placeItems: 'center',
        background: catCol(s.cat) + '22',
        color: catCol(s.cat),
        fontFamily: HB.mono,
        fontSize: 11,
        flexShrink: 0
      }
    }, s.glyph), /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 11.5,
        overflow: 'hidden',
        textOverflow: 'ellipsis',
        whiteSpace: 'nowrap'
      }
    }, s.title));
  })), /*#__PURE__*/React.createElement(PanelLabel, null, "AGENTS \xB7 DROP AS NODES"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: HB.mono,
      fontSize: 9,
      color: HB.inkMute,
      padding: '0 4px 6px',
      lineHeight: 1.4
    }
  }, "attaches into the open/selected domain & wires to its nodes"), DB.agents.map(function (a) {
    return /*#__PURE__*/React.createElement("button", {
      key: a.id,
      onClick: function onClick() {
        return addAgentNode(a.id);
      },
      title: "Drop onto the map",
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        width: '100%',
        textAlign: 'left',
        padding: '6px 8px',
        borderRadius: 7,
        border: 'none',
        background: 'transparent',
        cursor: 'pointer',
        color: HB.ink
      },
      onMouseEnter: function onMouseEnter(e) {
        return e.currentTarget.style.background = HB.paper2;
      },
      onMouseLeave: function onMouseLeave(e) {
        return e.currentTarget.style.background = 'transparent';
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        width: 20,
        height: 20,
        borderRadius: 6,
        display: 'grid',
        placeItems: 'center',
        background: HB.accentSoft,
        color: HB.accent,
        flexShrink: 0
      }
    }, /*#__PURE__*/React.createElement(CKIcon, {
      name: "agent",
      size: 12
    })), /*#__PURE__*/React.createElement("span", {
      style: {
        flex: 1,
        fontSize: 12,
        overflow: 'hidden',
        textOverflow: 'ellipsis',
        whiteSpace: 'nowrap'
      }
    }, a.name), /*#__PURE__*/React.createElement(CKIcon, {
      name: "plus",
      size: 12,
      color: HB.inkMute
    }));
  }))))), /*#__PURE__*/React.createElement("div", {
    ref: mapColRef,
    style: {
      flex: 1,
      position: 'relative',
      minWidth: 420
    },
    onDragOver: function onDragOver(e) {
      if (_toConsumableArray(e.dataTransfer.types).includes('application/x-atlas-node')) {
        e.preventDefault();
        e.dataTransfer.dropEffect = 'copy';
      }
    },
    onDrop: function onDrop(e) {
      var raw = e.dataTransfer.getData('application/x-atlas-node');
      if (!raw) return;
      e.preventDefault();
      var item;
      try {
        item = JSON.parse(raw);
      } catch (err) {
        return;
      }
      var w = window.__atlasToWorld && window.__atlasToWorld(e.clientX, e.clientY);
      var host = w && M.domains.find(function (d) {
        return w.x >= d.x && w.x <= d.x + d.w && w.y >= d.y && w.y <= d.y + d.h;
      });
      createFromLibrary(item, host && host.key, w && host ? {
        x: w.x - 76,
        y: w.y - 43
      } : null);
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "hb-blueprint",
    style: {
      position: 'absolute',
      inset: 0,
      opacity: 0.4,
      pointerEvents: 'none'
    }
  }), /*#__PURE__*/React.createElement(MapCanvas, {
    ref: canvas,
    M: M,
    vis: vis,
    sel: sel,
    selMode: selMode,
    expanded: expanded,
    agentsByNode: assign,
    activeWires: activeWires,
    onSelect: pickNode,
    onSelectBox: onSelectBox,
    onMarquee: onMarquee,
    onMove: moveNode,
    onMoveDomain: moveDomain,
    onToggleDomain: toggleDomain,
    onToggleNode: toggleNode,
    openNodes: openNodes,
    onPickDomain: pickDomain,
    onPickField: pickField,
    onDomainContext: onDomainContext,
    onFieldContext: onFieldContext,
    onInspect: inspectNode,
    onNodeContext: onNodeContext,
    onConnect: connectNodes,
    onWireContext: onWireContext,
    onPickWire: pickWire,
    query: query,
    onOffGrid: setOffGrid,
    hostW: mapW
  }), offGrid.length > 0 && !offGridDismissed && /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      bottom: 78,
      left: '50%',
      transform: 'translateX(-50%)',
      zIndex: 6,
      display: 'flex',
      alignItems: 'center',
      gap: 10,
      padding: '8px 12px',
      borderRadius: 9,
      background: HB.paper2,
      border: "1px solid ".concat(HB.amber),
      boxShadow: '0 8px 24px rgba(0,0,0,.5)',
      whiteSpace: 'nowrap'
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: HB.mono,
      fontSize: 9,
      color: HB.amber,
      letterSpacing: '0.14em'
    }
  }, "OFF GRID"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: HB.sans,
      fontSize: 12,
      color: HB.inkSoft
    }
  }, offGrid.length === 1 ? '1 domain is' : offGrid.length + ' domains are', " off the layout grid \u2014 left out of \u201Cframe all\u201D so the map keeps its scale."), /*#__PURE__*/React.createElement("button", {
    onClick: autoOrganize,
    style: {
      fontFamily: HB.mono,
      fontSize: 10,
      letterSpacing: '0.06em',
      padding: '4px 9px',
      borderRadius: 6,
      border: "1px solid ".concat(HB.accent),
      background: 'transparent',
      color: HB.accent,
      cursor: 'pointer'
    }
  }, "TIDY UP"), /*#__PURE__*/React.createElement("button", {
    onClick: function onClick() {
      return setOffGridDismissed(true);
    },
    title: "Keep the placement",
    style: {
      fontFamily: HB.mono,
      fontSize: 11,
      padding: '3px 7px',
      borderRadius: 6,
      border: "1px solid ".concat(HB.line),
      background: 'transparent',
      color: HB.inkMute,
      cursor: 'pointer'
    }
  }, "\u2715")), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      top: 12,
      left: 14,
      right: 372,
      display: 'flex',
      alignItems: 'center',
      gap: 8,
      minWidth: 0,
      pointerEvents: 'none'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 6,
      padding: '6px 11px',
      borderRadius: 8,
      background: HB.card,
      border: "1px solid ".concat(HB.line),
      boxShadow: '0 3px 12px rgba(0,0,0,.08)',
      flexShrink: 0,
      pointerEvents: 'auto'
    }
  }, /*#__PURE__*/React.createElement(CKIcon, {
    name: "map",
    size: 13,
    color: HB.accent
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: HB.mono,
      fontSize: 11.5,
      color: HB.ink,
      whiteSpace: 'nowrap',
      flexShrink: 0
    }
  }, "Federated model"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: HB.mono,
      fontSize: 10,
      color: HB.inkMute,
      whiteSpace: 'nowrap'
    }
  }, "\xB7 ", M.domains.length, " domains")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 6,
      padding: '6px 10px',
      borderRadius: 8,
      background: HB.card,
      border: "1px solid ".concat(HB.line),
      flex: '0 1 160px',
      minWidth: 92,
      boxSizing: 'border-box',
      pointerEvents: 'auto'
    }
  }, /*#__PURE__*/React.createElement(CKIcon, {
    name: "search",
    size: 12,
    color: HB.inkMute,
    style: {
      flexShrink: 0
    }
  }), /*#__PURE__*/React.createElement("input", {
    value: query,
    onChange: function onChange(e) {
      return setQuery(e.target.value);
    },
    placeholder: "find\u2026",
    style: {
      flex: 1,
      minWidth: 0,
      width: 0,
      border: 'none',
      background: 'transparent',
      color: HB.ink,
      fontSize: 12,
      outline: 'none'
    }
  }))), /*#__PURE__*/React.createElement(ScaleLadder, {
    level: scaleLevel,
    onClimb: climbTo,
    depth: modelDepth
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      top: 12,
      right: 14,
      fontFamily: HB.mono,
      fontSize: 9.5,
      color: HB.inkSoft,
      letterSpacing: '0.1em',
      whiteSpace: 'nowrap',
      padding: '6px 11px',
      background: HB.card,
      border: "1px solid ".concat(HB.line),
      borderRadius: 8
    }
  }, "ZOOM TO RESOLVE \xB7 click a domain header to open/collapse"), function () {
    var selDom = (sel.domains || new Set()).size;
    var selCount = sel.nodes.size + selDom;
    if (selCount === 0) return null;
    var intoField = selDom >= 1;
    var canGroup = selCount >= 2;
    var label = selDom && sel.nodes.size ? "".concat(selDom, " domain").concat(selDom > 1 ? 's' : '', " + ").concat(sel.nodes.size, " node").concat(sel.nodes.size > 1 ? 's' : '') : selDom ? "".concat(selDom, " domain").concat(selDom > 1 ? 's' : '') : "".concat(sel.nodes.size, " node").concat(sel.nodes.size > 1 ? 's' : '');
    return /*#__PURE__*/React.createElement("div", {
      style: {
        position: 'absolute',
        bottom: 80,
        left: '50%',
        transform: 'translateX(-50%)',
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        padding: '8px 12px',
        borderRadius: 12,
        background: HB.paper2,
        color: HB.ink,
        border: "1px solid ".concat(HB.line),
        boxShadow: '0 14px 40px rgba(0,0,0,.5)'
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        fontFamily: HB.mono,
        fontSize: 11.5
      }
    }, label, " selected"), /*#__PURE__*/React.createElement("div", {
      style: {
        width: 1,
        height: 18,
        background: HB.line
      }
    }), canGroup && /*#__PURE__*/React.createElement("button", {
      onClick: groupAny,
      title: "Make one node out of what you picked",
      style: {
        display: 'inline-flex',
        alignItems: 'center',
        gap: 6,
        padding: '5px 12px',
        borderRadius: 7,
        border: 'none',
        background: HB.accent,
        color: window.AH && window.AH.onFill || '#180f08',
        cursor: 'pointer',
        fontFamily: HB.mono,
        fontSize: 11,
        fontWeight: 700
      }
    }, "\u229E Group"), sel.nodes.size > 0 && /*#__PURE__*/React.createElement(DarkBtn, {
      onClick: function onClick() {
        return requestDelete(_toConsumableArray(sel.nodes));
      },
      icon: "trash"
    }, "Delete"), /*#__PURE__*/React.createElement(DarkBtn, {
      onClick: clearSel,
      icon: "x"
    }, "Clear"));
  }(), function () {
    var selCount = sel.nodes.size + (sel.domains || new Set()).size;
    if (selCount > 0) return null;
    if (offGrid.length > 0 && !offGridDismissed) return null; // off-grid notice owns this slot
    return /*#__PURE__*/React.createElement("div", {
      style: {
        position: 'absolute',
        bottom: 80,
        left: '50%',
        transform: 'translateX(-50%)',
        display: 'flex',
        alignItems: 'center',
        gap: 9,
        padding: '7px 14px',
        borderRadius: 999,
        background: selMode ? HB.accent : HB.cardHi,
        color: selMode ? '#fff' : HB.inkSoft,
        border: "1px solid ".concat(selMode ? HB.accent : HB.line),
        boxShadow: '0 6px 20px rgba(0,0,0,.12)',
        fontFamily: HB.mono,
        fontSize: 11,
        whiteSpace: 'nowrap',
        pointerEvents: 'none'
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 13
      }
    }, "\u229E"), selMode ? /*#__PURE__*/React.createElement("span", null, /*#__PURE__*/React.createElement("b", null, "Drag a box"), " over domains (or nodes) \u2014 then ", /*#__PURE__*/React.createElement("b", null, "Group")) : /*#__PURE__*/React.createElement("span", null, /*#__PURE__*/React.createElement("b", {
      style: {
        color: HB.accent
      }
    }, "\u21E7-drag"), " a box, or ", /*#__PURE__*/React.createElement("b", {
      style: {
        color: HB.accent
      }
    }, "\u21E7-click"), ", to multi-select \u2192 ", /*#__PURE__*/React.createElement("b", null, "Group")));
  }(), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      bottom: 16,
      left: '50%',
      transform: 'translateX(-50%)',
      width: 540,
      maxWidth: '90%'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 10,
      padding: '0 14px',
      height: 46,
      background: HB.cardHi,
      border: "1.5px solid ".concat(HB.line),
      borderRadius: 999,
      boxShadow: '0 12px 34px rgba(0,0,0,.16)'
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      color: HB.accent
    }
  }, /*#__PURE__*/React.createElement(CKIcon, {
    name: "brain",
    size: 17
  })), /*#__PURE__*/React.createElement("input", {
    value: cmd,
    onChange: function onChange(e) {
      return setCmd(e.target.value);
    },
    onKeyDown: function onKeyDown(e) {
      return e.key === 'Enter' && runCmd();
    },
    placeholder: "Command \u2014 \u201Center brain\u201D, \u201Coperate models\u201D, \u201Cmacro\u201D, \u201Chealth\u201D\u2026",
    style: {
      flex: 1,
      border: 'none',
      background: 'transparent',
      color: HB.ink,
      fontSize: 13,
      outline: 'none',
      fontFamily: HB.sans
    }
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: HB.mono,
      fontSize: 10,
      color: HB.inkSoft
    }
  }, "\u21B5")))), /*#__PURE__*/React.createElement("div", {
    style: {
      width: rightW,
      flexShrink: 1,
      minWidth: 216,
      borderLeft: "1px solid ".concat(HB.line),
      background: HB.card,
      display: 'flex',
      flexDirection: 'column',
      minHeight: 0
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      padding: '11px 14px 10px',
      borderBottom: "1px solid ".concat(HB.line),
      flexShrink: 0,
      display: 'flex',
      alignItems: 'center',
      gap: 8
    }
  }, /*#__PURE__*/React.createElement(CKIcon, {
    name: "sliders",
    size: 12
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: HB.mono,
      fontSize: 10.5,
      letterSpacing: '0.08em',
      color: HB.ink,
      flex: 1
    }
  }, "PARAMETERS"), sel.nodes.size || sel.domain || sel.field || (sel.domains || new Set()).size ? /*#__PURE__*/React.createElement("button", {
    onClick: clearSel,
    title: "Clear selection",
    style: {
      fontFamily: HB.mono,
      fontSize: 10,
      padding: '3px 7px',
      borderRadius: 5,
      border: "1px solid ".concat(HB.line),
      background: 'transparent',
      color: HB.inkMute,
      cursor: 'pointer'
    }
  }, "clear") : /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: HB.mono,
      fontSize: 9,
      color: HB.inkSoft
    }
  }, "nothing selected")), /*#__PURE__*/React.createElement("div", {
    className: "hb-scroll",
    style: {
      flex: 1,
      overflow: 'auto',
      minHeight: 0
    }
  }, inspectPanel))), domModal && /*#__PURE__*/React.createElement(NameModal, {
    title: "Create a domain",
    placeholder: "e.g. Compliance & Audit",
    colors: DOM_COLS,
    onSave: function onSave(name, col) {
      addDomain(name, col);
      setDomModal(false);
    },
    onClose: function onClose() {
      return setDomModal(false);
    }
  }), ctx && /*#__PURE__*/React.createElement(ContextMenu, {
    ctx: ctx,
    M: M,
    node: ctx.type === 'node' ? M.nodes.find(function (n) {
      return n.id === ctx.id;
    }) : null,
    domain: ctx.type === 'domain' ? M.domains.find(function (d) {
      return d.key === ctx.key;
    }) : null,
    field: ctx.type === 'field' ? (M.fields || []).find(function (f) {
      return f.id === ctx.id;
    }) : null,
    openNodes: openNodes,
    selCount: sel.nodes.size + (sel.domains || new Set()).size,
    nodeDomGrouped: ctx.type === 'node' ? !!(M.domains.find(function (d) {
      return d.key === (M.nodes.find(function (n) {
        return n.id === ctx.id;
      }) || {}).dom;
    }) || {}).grouped : false,
    nodeField: ctx.type === 'node' ? fieldOf((M.nodes.find(function (n) {
      return n.id === ctx.id;
    }) || {}).dom) : null,
    domField: ctx.type === 'domain' ? fieldOf(ctx.key) : null,
    onClose: function onClose() {
      return setCtx(null);
    },
    actions: {
      run: function run() {
        return runNode(ctx.id);
      },
      watch: function watch() {
        return addWatcher(ctx.id);
      },
      pipeline: function pipeline() {
        return toggleNode(ctx.id, !openNodes.has(ctx.id));
      },
      freeze: function freeze() {
        return freezeNode(ctx.id);
      },
      duplicate: function duplicate() {
        return duplicateNode(ctx.id);
      },
      disconnect: function disconnect() {
        return disconnectAll(ctx.id);
      },
      del: function del() {
        return requestDelete([ctx.id]);
      },
      cutWire: function cutWire() {
        return disconnectWire(ctx.a, ctx.b);
      },
      group: groupAny,
      ungroupGrandFromNode: function ungroupGrandFromNode() {
        var n = M.nodes.find(function (x) {
          return x.id === ctx.id;
        });
        if (n) ungroupDomain(n.dom);
      },
      ungroupGrand: function ungroupGrand() {
        return ungroupDomain(ctx.key);
      },
      ungroupFieldFromDomain: function ungroupFieldFromDomain() {
        var f = fieldOf(ctx.key);
        if (f) _ungroupField(f.id);
      },
      ungroupField: function ungroupField() {
        return _ungroupField(ctx.id);
      },
      openDomain: function openDomain() {
        var d = M.domains.find(function (x) {
          return x.key === ctx.key;
        });
        toggleDomain(ctx.key, !(expanded.open.has(ctx.key) || !expanded.collapsed.has(ctx.key)));
        pickDomain(ctx.key);
      },
      enterDomain: function enterDomain() {
        return focusDomain(ctx.key);
      },
      addNodeHere: function addNodeHere() {
        return addNode(ctx.key);
      },
      groupField: groupIntoField
    }
  }), confirmDel && /*#__PURE__*/React.createElement(ConfirmModal, {
    count: confirmDel.ids.length,
    names: confirmDel.ids.map(function (id) {
      return (M.nodes.find(function (n) {
        return n.id === id;
      }) || {}).title;
    }).filter(Boolean),
    wires: M.wires.filter(function (w) {
      return confirmDel.ids.includes(w.a) || confirmDel.ids.includes(w.b);
    }).length,
    onCancel: function onCancel() {
      return setConfirmDel(null);
    },
    onConfirm: function onConfirm() {
      delNodes(confirmDel.ids);
      setConfirmDel(null);
    }
  }), toast && /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'fixed',
      bottom: 74,
      left: '50%',
      transform: 'translateX(-50%)',
      zIndex: 80,
      background: HB.paper2,
      color: HB.ink,
      border: "1px solid ".concat(HB.line),
      borderRadius: 999,
      padding: '8px 16px',
      fontSize: 12,
      fontFamily: HB.mono,
      boxShadow: '0 14px 40px rgba(0,0,0,.3)',
      display: 'flex',
      alignItems: 'center',
      gap: 8
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      color: HB.accent
    }
  }, /*#__PURE__*/React.createElement(CKIcon, {
    name: "check",
    size: 13
  })), toast));
}

/* left-panel atoms */
var A_RAIL = [{
  id: 'library',
  title: 'Library · drag onto the map',
  svg: /*#__PURE__*/React.createElement("svg", {
    width: "14",
    height: "14",
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: "1.8"
  }, /*#__PURE__*/React.createElement("rect", {
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
  }))
}, {
  id: 'agents',
  title: 'Agents · activity, sessions, history',
  svg: /*#__PURE__*/React.createElement("svg", {
    width: "14",
    height: "14",
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: "1.8"
  }, /*#__PURE__*/React.createElement("polygon", {
    points: "12 2 15 8 22 9 17 14 18 21 12 17.7 6 21 7 14 2 9 9 8"
  }))
}, {
  id: 'index',
  title: 'Index · every domain',
  svg: /*#__PURE__*/React.createElement("svg", {
    width: "14",
    height: "14",
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: "1.8"
  }, /*#__PURE__*/React.createElement("path", {
    d: "M4 6h16M4 12h16M4 18h16"
  }))
}, {
  id: 'view',
  title: 'View · what the map shows',
  svg: /*#__PURE__*/React.createElement("svg", {
    width: "14",
    height: "14",
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: "1.8"
  }, /*#__PURE__*/React.createElement("path", {
    d: "M1.5 12S5 5.5 12 5.5 22.5 12 22.5 12 19 18.5 12 18.5 1.5 12 1.5 12z"
  }), /*#__PURE__*/React.createElement("circle", {
    cx: "12",
    cy: "12",
    r: "3"
  }))
}];
var ARailIcon = function ARailIcon(_ref14) {
  var active = _ref14.active,
    brand = _ref14.brand,
    onClick = _ref14.onClick,
    title = _ref14.title,
    children = _ref14.children;
  var lit = active || brand;
  return /*#__PURE__*/React.createElement("button", {
    onClick: onClick,
    title: title,
    style: {
      width: 30,
      height: 30,
      padding: 0,
      border: 0,
      borderRadius: HB.rad.md,
      background: lit ? HB.accentSoft : 'transparent',
      color: lit ? HB.accent : HB.inkSoft,
      cursor: 'pointer',
      display: 'grid',
      placeItems: 'center',
      position: 'relative',
      boxShadow: brand ? "inset 0 0 0 1px ".concat(HB.accent, "55") : 'none'
    },
    onMouseEnter: function onMouseEnter(e) {
      return !lit && (e.currentTarget.style.background = HB.paper2);
    },
    onMouseLeave: function onMouseLeave(e) {
      return !lit && (e.currentTarget.style.background = 'transparent');
    }
  }, active && !brand && /*#__PURE__*/React.createElement("span", {
    style: {
      position: 'absolute',
      left: -7,
      top: 6,
      bottom: 6,
      width: 2,
      background: HB.accent,
      borderRadius: 2
    }
  }), children);
};
var AtlasIconRail = function AtlasIconRail(_ref15) {
  var panel = _ref15.panel,
    setPanel = _ref15.setPanel,
    onFrameAll = _ref15.onFrameAll,
    onTidy = _ref15.onTidy;
  return /*#__PURE__*/React.createElement("div", {
    style: {
      background: HB.paper,
      borderRight: "1px solid ".concat(HB.line),
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      padding: '10px 0 8px',
      gap: 4
    }
  }, /*#__PURE__*/React.createElement(ARailIcon, {
    brand: true,
    onClick: onFrameAll,
    title: "Frame the whole model"
  }, /*#__PURE__*/React.createElement("svg", {
    width: "15",
    height: "15",
    viewBox: "0 0 24 24",
    fill: "none"
  }, /*#__PURE__*/React.createElement("path", {
    d: "M3 21 V12 a9 9 0 0 1 18 0 V21",
    stroke: HB.accent,
    strokeWidth: "2",
    strokeLinecap: "round"
  }), /*#__PURE__*/React.createElement("circle", {
    cx: "12",
    cy: "8.5",
    r: "1.5",
    fill: HB.accent
  }))), /*#__PURE__*/React.createElement("div", {
    style: {
      height: 6
    }
  }), A_RAIL.map(function (it) {
    return /*#__PURE__*/React.createElement(ARailIcon, {
      key: it.id,
      active: panel === it.id,
      onClick: function onClick() {
        return setPanel(it.id);
      },
      title: it.title
    }, it.svg);
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1
    }
  }), /*#__PURE__*/React.createElement(ARailIcon, {
    onClick: onTidy,
    title: "Tidy up \xB7 wire-aware layout"
  }, /*#__PURE__*/React.createElement("svg", {
    width: "14",
    height: "14",
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: "1.8"
  }, /*#__PURE__*/React.createElement("rect", {
    x: "3",
    y: "3",
    width: "8",
    height: "8",
    rx: "1"
  }), /*#__PURE__*/React.createElement("rect", {
    x: "13",
    y: "3",
    width: "8",
    height: "8",
    rx: "1"
  }), /*#__PURE__*/React.createElement("rect", {
    x: "3",
    y: "13",
    width: "8",
    height: "8",
    rx: "1"
  }), /*#__PURE__*/React.createElement("path", {
    d: "M13 17h8"
  }))));
};
var PanelLabel = function PanelLabel(_ref16) {
  var children = _ref16.children,
    right = _ref16.right;
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      fontFamily: HB.mono,
      fontSize: 8.5,
      color: HB.inkMute,
      letterSpacing: '0.16em',
      padding: '15px 6px 8px'
    }
  }, /*#__PURE__*/React.createElement("span", null, children), right);
};
var miniLink = {
  border: 'none',
  background: 'transparent',
  color: HB.accent,
  cursor: 'pointer',
  fontFamily: HB.mono,
  fontSize: 9,
  letterSpacing: '0.1em'
};
// PANEL CHROME — one spec, shared by the left (Inspect/View/Index) and right (Agentic) rails
// so both sides of the map line up: same tab height, same section padding, same label.
var ltab = function ltab(on) {
  return {
    flex: 1,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
    padding: '10px 0',
    border: 'none',
    borderBottom: "2px solid ".concat(on ? HB.accent : 'transparent'),
    background: 'transparent',
    cursor: 'pointer',
    fontFamily: HB.mono,
    fontSize: 10.5,
    letterSpacing: '0.06em',
    color: on ? HB.ink : HB.inkMute
  };
};
var segBtn = function segBtn(on) {
  return {
    flex: 1,
    padding: '6px 0',
    borderRadius: 6,
    border: 'none',
    cursor: 'pointer',
    fontFamily: HB.mono,
    fontSize: 10.5,
    background: on ? HB.card : 'transparent',
    color: on ? HB.accentHi : HB.inkSoft,
    boxShadow: on ? '0 1px 4px rgba(0,0,0,.08)' : 'none'
  };
};
var visRow = function visRow(on) {
  return {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    width: '100%',
    textAlign: 'left',
    padding: '6px 8px',
    borderRadius: 7,
    border: 'none',
    background: 'transparent',
    cursor: 'default',
    color: on ? HB.ink : HB.inkMute,
    fontSize: 12,
    opacity: on ? 1 : 0.7
  };
};
var MiniBtn = function MiniBtn(_ref17) {
  var children = _ref17.children,
    onClick = _ref17.onClick,
    on = _ref17.on,
    icon = _ref17.icon;
  return /*#__PURE__*/React.createElement("button", {
    onClick: onClick,
    style: {
      flex: 1,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      gap: 6,
      padding: '7px 0',
      borderRadius: 7,
      cursor: 'pointer',
      fontFamily: HB.mono,
      fontSize: 10.5,
      border: "1px solid ".concat(on ? HB.accent : HB.line),
      background: on ? HB.accentSoft : HB.card,
      color: on ? HB.accentHi : HB.inkSoft
    }
  }, /*#__PURE__*/React.createElement(CKIcon, {
    name: icon,
    size: 12
  }), children);
};
var ToggleRow = function ToggleRow(_ref18) {
  var label = _ref18.label,
    on = _ref18.on,
    onClick = _ref18.onClick;
  return /*#__PURE__*/React.createElement("button", {
    onClick: onClick,
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 9,
      width: '100%',
      padding: '7px 8px',
      borderRadius: 7,
      border: 'none',
      background: 'transparent',
      cursor: 'pointer',
      color: HB.ink,
      fontSize: 12
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: 30,
      height: 17,
      borderRadius: 99,
      background: on ? HB.accent : HB.line,
      position: 'relative',
      flexShrink: 0
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      position: 'absolute',
      top: 2,
      left: on ? 15 : 2,
      width: 13,
      height: 13,
      borderRadius: '50%',
      background: '#fff',
      transition: 'left .15s'
    }
  })), label);
};
var DarkBtn = function DarkBtn(_ref19) {
  var children = _ref19.children,
    onClick = _ref19.onClick,
    icon = _ref19.icon;
  return /*#__PURE__*/React.createElement("button", {
    onClick: onClick,
    style: {
      display: 'inline-flex',
      alignItems: 'center',
      gap: 5,
      padding: '5px 10px',
      borderRadius: 7,
      border: '1px solid #ffffff22',
      background: '#ffffff10',
      color: HB.ink,
      cursor: 'pointer',
      fontFamily: HB.mono,
      fontSize: 11
    }
  }, /*#__PURE__*/React.createElement(CKIcon, {
    name: icon,
    size: 12
  }), children);
};

/* right-click contextual menu (node · domain · field · wire) */
function ContextMenu(_ref20) {
  var ctx = _ref20.ctx,
    node = _ref20.node,
    domain = _ref20.domain,
    field = _ref20.field,
    openNodes = _ref20.openNodes,
    selCount = _ref20.selCount,
    nodeDomGrouped = _ref20.nodeDomGrouped,
    nodeField = _ref20.nodeField,
    domField = _ref20.domField,
    actions = _ref20.actions,
    onClose = _ref20.onClose;
  React.useEffect(function () {
    var h = function h() {
      return onClose();
    };
    window.addEventListener('click', h);
    window.addEventListener('contextmenu', h);
    return function () {
      window.removeEventListener('click', h);
      window.removeEventListener('contextmenu', h);
    };
  }, []);
  var items;
  if (ctx.type === 'wire') items = [{
    icon: 'trash',
    label: 'Cut this wire',
    fn: actions.cutWire,
    danger: true
  }];else if (ctx.type === 'field') items = [{
    icon: 'eye',
    label: 'Focus field',
    fn: function fn() {},
    dim: true
  }, {
    icon: 'grid',
    label: 'Ungroup field — keep domains',
    fn: actions.ungroupField
  }];else if (ctx.type === 'domain') items = [{
    icon: 'eye',
    label: 'Open / collapse',
    fn: actions.openDomain
  }, {
    icon: 'layout',
    label: 'Enter domain',
    fn: actions.enterDomain
  }, {
    icon: 'plus',
    label: 'Add node',
    fn: actions.addNodeHere
  }, {
    sep: true
  }].concat(_toConsumableArray(selCount >= 2 ? [{
    icon: 'grid',
    label: 'Group selection',
    fn: actions.groupField,
    accent: true
  }] : []), _toConsumableArray(domain && domain.grouped ? [{
    icon: 'grid',
    label: 'Ungroup',
    fn: actions.ungroupGrand
  }] : []), _toConsumableArray(domField ? [{
    icon: 'grid',
    label: 'Ungroup from parent',
    fn: actions.ungroupFieldFromDomain
  }] : []));else items = [].concat(_toConsumableArray(selCount >= 2 ? [{
    icon: 'grid',
    label: 'Group selection',
    fn: actions.group,
    accent: true
  }, {
    sep: true
  }] : []), [{
    icon: 'play',
    label: node && node.frozen ? 'Run (frozen)' : 'Run node',
    fn: actions.run,
    dim: node && node.frozen
  }, {
    icon: 'eye',
    label: 'Add watcher',
    fn: actions.watch
  }, {
    icon: 'layout',
    label: openNodes.has(ctx.id) ? 'Collapse pipeline' : 'Open pipeline',
    fn: actions.pipeline
  }, {
    sep: true
  }, {
    icon: 'lock',
    label: node && node.frozen ? 'Unfreeze' : 'Freeze node',
    fn: actions.freeze,
    on: node && node.frozen
  }, {
    icon: 'plus',
    label: 'Duplicate',
    fn: actions.duplicate
  }, {
    icon: 'link',
    label: 'Disconnect all wires',
    fn: actions.disconnect
  }], _toConsumableArray(nodeDomGrouped ? [{
    sep: true
  }, {
    icon: 'grid',
    label: 'Ungroup',
    fn: actions.ungroupGrandFromNode
  }] : []), [{
    sep: true
  }, {
    icon: 'trash',
    label: 'Delete node…',
    fn: actions.del,
    danger: true
  }]);
  var W = 224,
    est = items.length * 34 + 10;
  var x = Math.min(ctx.x, window.innerWidth - W - 8),
    y = Math.min(ctx.y, window.innerHeight - est - 8);
  var head = ctx.type === 'node' && node ? {
    tag: (node.cat || '').toUpperCase() + (node.frozen ? ' · FROZEN' : ''),
    title: node.title
  } : ctx.type === 'domain' && domain ? {
    tag: domain.grouped ? 'DOMAIN · GROUPED' : 'DOMAIN · GROUP OF NODES',
    title: domain.title
  } : ctx.type === 'field' && field ? {
    tag: 'FIELD · GROUP OF DOMAINS',
    title: field.title
  } : null;
  return /*#__PURE__*/React.createElement("div", {
    onClick: function onClick(e) {
      return e.stopPropagation();
    },
    onContextMenu: function onContextMenu(e) {
      e.preventDefault();
      e.stopPropagation();
    },
    style: {
      position: 'fixed',
      left: x,
      top: y,
      width: W,
      zIndex: 200,
      background: HB.card,
      border: "1px solid ".concat(HB.line),
      borderRadius: 10,
      boxShadow: '0 16px 50px rgba(0,0,0,.3)',
      padding: 5,
      fontFamily: HB.sans
    }
  }, head && /*#__PURE__*/React.createElement("div", {
    style: {
      padding: '7px 9px 8px',
      borderBottom: "1px solid ".concat(HB.lineSoft),
      marginBottom: 4
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: HB.mono,
      fontSize: 8,
      color: HB.inkMute,
      letterSpacing: '0.14em'
    }
  }, head.tag), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 13,
      fontWeight: 600,
      color: HB.ink,
      overflow: 'hidden',
      textOverflow: 'ellipsis',
      whiteSpace: 'nowrap'
    }
  }, head.title)), items.map(function (it, i) {
    return it.sep ? /*#__PURE__*/React.createElement("div", {
      key: i,
      style: {
        height: 1,
        background: HB.lineSoft,
        margin: '4px 6px'
      }
    }) : /*#__PURE__*/React.createElement("button", {
      key: i,
      onClick: function onClick() {
        it.fn();
        onClose();
      },
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        width: '100%',
        textAlign: 'left',
        padding: '8px 9px',
        borderRadius: 7,
        border: 'none',
        background: it.on ? HB.accentSoft : 'transparent',
        cursor: 'pointer',
        color: it.danger ? HB.red : it.accent ? HB.accentHi : it.dim ? HB.inkMute : HB.ink,
        fontSize: 12.5,
        fontWeight: it.accent ? 700 : 400,
        opacity: it.dim ? 0.6 : 1
      },
      onMouseEnter: function onMouseEnter(e) {
        return e.currentTarget.style.background = it.danger ? HB.red + '14' : HB.paper2;
      },
      onMouseLeave: function onMouseLeave(e) {
        return e.currentTarget.style.background = it.on ? HB.accentSoft : 'transparent';
      }
    }, /*#__PURE__*/React.createElement(CKIcon, {
      name: it.icon,
      size: 14
    }), it.label);
  }));
}

/* delete-with-warning */
function ConfirmModal(_ref21) {
  var count = _ref21.count,
    names = _ref21.names,
    wires = _ref21.wires,
    onCancel = _ref21.onCancel,
    onConfirm = _ref21.onConfirm;
  return /*#__PURE__*/React.createElement("div", {
    onClick: onCancel,
    style: {
      position: 'fixed',
      inset: 0,
      zIndex: 210,
      background: 'rgba(0,0,0,0.5)',
      display: 'grid',
      placeItems: 'center',
      animation: 'hbFade .14s'
    }
  }, /*#__PURE__*/React.createElement("div", {
    onClick: function onClick(e) {
      return e.stopPropagation();
    },
    style: {
      width: 380,
      background: HB.card,
      border: "1px solid ".concat(HB.line),
      borderRadius: 14,
      padding: 20,
      boxShadow: '0 30px 80px rgba(0,0,0,.6)'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 10,
      marginBottom: 12
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: 34,
      height: 34,
      borderRadius: 9,
      display: 'grid',
      placeItems: 'center',
      background: HB.red + '1e',
      color: HB.red,
      flexShrink: 0
    }
  }, /*#__PURE__*/React.createElement(CKIcon, {
    name: "trash",
    size: 17
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: HB.serif,
      fontSize: 21,
      letterSpacing: '-0.01em'
    }
  }, "Delete ", count > 1 ? "".concat(count, " nodes") : 'node', "?")), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 13,
      color: HB.inkSoft,
      lineHeight: 1.55
    }
  }, count === 1 && names[0] ? /*#__PURE__*/React.createElement(React.Fragment, null, "This removes ", /*#__PURE__*/React.createElement("b", {
    style: {
      color: HB.ink
    }
  }, names[0]), " from the model.") : /*#__PURE__*/React.createElement(React.Fragment, null, "This removes ", /*#__PURE__*/React.createElement("b", {
    style: {
      color: HB.ink
    }
  }, count, " nodes"), " from the model."), wires > 0 && /*#__PURE__*/React.createElement(React.Fragment, null, " It also cuts ", /*#__PURE__*/React.createElement("b", {
    style: {
      color: HB.ink
    }
  }, wires), " wire", wires > 1 ? 's' : '', " connected to ", count > 1 ? 'them' : 'it', "."), " This can't be undone."), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      justifyContent: 'flex-end',
      gap: 8,
      marginTop: 18
    }
  }, /*#__PURE__*/React.createElement(HBtn, {
    onClick: onCancel
  }, "Cancel"), /*#__PURE__*/React.createElement(HBtn, {
    onClick: onConfirm,
    style: {
      background: HB.red,
      borderColor: HB.red,
      color: '#fff'
    }
  }, /*#__PURE__*/React.createElement(CKIcon, {
    name: "trash",
    size: 13
  }), "Delete"))));
}
Object.assign(window, {
  AtlasCockpit: AtlasCockpit,
  STATUS_ORDER: STATUS_ORDER,
  CAT_LIST: CAT_LIST,
  DOM_COLS: DOM_COLS
});
ReactDOM.createRoot(document.getElementById('root')).render(/*#__PURE__*/React.createElement(AtlasCockpit, null));
