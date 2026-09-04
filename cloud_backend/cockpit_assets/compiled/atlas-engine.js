function _typeof(o) { "@babel/helpers - typeof"; return _typeof = "function" == typeof Symbol && "symbol" == typeof Symbol.iterator ? function (o) { return typeof o; } : function (o) { return o && "function" == typeof Symbol && o.constructor === Symbol && o !== Symbol.prototype ? "symbol" : typeof o; }, _typeof(o); }
function ownKeys(e, r) { var t = Object.keys(e); if (Object.getOwnPropertySymbols) { var o = Object.getOwnPropertySymbols(e); r && (o = o.filter(function (r) { return Object.getOwnPropertyDescriptor(e, r).enumerable; })), t.push.apply(t, o); } return t; }
function _objectSpread(e) { for (var r = 1; r < arguments.length; r++) { var t = null != arguments[r] ? arguments[r] : {}; r % 2 ? ownKeys(Object(t), !0).forEach(function (r) { _defineProperty(e, r, t[r]); }) : Object.getOwnPropertyDescriptors ? Object.defineProperties(e, Object.getOwnPropertyDescriptors(t)) : ownKeys(Object(t)).forEach(function (r) { Object.defineProperty(e, r, Object.getOwnPropertyDescriptor(t, r)); }); } return e; }
function _defineProperty(e, r, t) { return (r = _toPropertyKey(r)) in e ? Object.defineProperty(e, r, { value: t, enumerable: !0, configurable: !0, writable: !0 }) : e[r] = t, e; }
function _toPropertyKey(t) { var i = _toPrimitive(t, "string"); return "symbol" == _typeof(i) ? i : i + ""; }
function _toPrimitive(t, r) { if ("object" != _typeof(t) || !t) return t; var e = t[Symbol.toPrimitive]; if (void 0 !== e) { var i = e.call(t, r || "default"); if ("object" != _typeof(i)) return i; throw new TypeError("@@toPrimitive must return a primitive value."); } return ("string" === r ? String : Number)(t); }
function _slicedToArray(r, e) { return _arrayWithHoles(r) || _iterableToArrayLimit(r, e) || _unsupportedIterableToArray(r, e) || _nonIterableRest(); }
function _nonIterableRest() { throw new TypeError("Invalid attempt to destructure non-iterable instance.\nIn order to be iterable, non-array objects must have a [Symbol.iterator]() method."); }
function _iterableToArrayLimit(r, l) { var t = null == r ? null : "undefined" != typeof Symbol && r[Symbol.iterator] || r["@@iterator"]; if (null != t) { var e, n, i, u, a = [], f = !0, o = !1; try { if (i = (t = t.call(r)).next, 0 === l) { if (Object(t) !== t) return; f = !1; } else for (; !(f = (e = i.call(t)).done) && (a.push(e.value), a.length !== l); f = !0); } catch (r) { o = !0, n = r; } finally { try { if (!f && null != t["return"] && (u = t["return"](), Object(u) !== u)) return; } finally { if (o) throw n; } } return a; } }
function _arrayWithHoles(r) { if (Array.isArray(r)) return r; }
function _toConsumableArray(r) { return _arrayWithoutHoles(r) || _iterableToArray(r) || _unsupportedIterableToArray(r) || _nonIterableSpread(); }
function _nonIterableSpread() { throw new TypeError("Invalid attempt to spread non-iterable instance.\nIn order to be iterable, non-array objects must have a [Symbol.iterator]() method."); }
function _unsupportedIterableToArray(r, a) { if (r) { if ("string" == typeof r) return _arrayLikeToArray(r, a); var t = {}.toString.call(r).slice(8, -1); return "Object" === t && r.constructor && (t = r.constructor.name), "Map" === t || "Set" === t ? Array.from(r) : "Arguments" === t || /^(?:Ui|I)nt(?:8|16|32)(?:Clamped)?Array$/.test(t) ? _arrayLikeToArray(r, a) : void 0; } }
function _iterableToArray(r) { if ("undefined" != typeof Symbol && null != r[Symbol.iterator] || null != r["@@iterator"]) return Array.from(r); }
function _arrayWithoutHoles(r) { if (Array.isArray(r)) return _arrayLikeToArray(r); }
function _arrayLikeToArray(r, a) { (null == a || a > r.length) && (a = r.length); for (var e = 0, n = Array(a); e < a; e++) n[e] = r[e]; return n; }
// atlas-engine.jsx — the Grand Map as ONE federated BIM-style model.
// Everything in a single coordinated graph: all 14 domains, all 203 nodes, all
// 389 wires — at once. Level-of-detail by zoom: zoomed out you see domain volumes
// wired together; zoom in and the nodes resolve INSIDE their domains with live
// wiring. Domains can also be expanded/collapsed in place. Vellum drafting (HB).

var _window = window,
  HB = _window.HB;
var NW = 152,
  NHt = 86;
var STC = {
  live: HB.green,
  partial: HB.amber,
  vision: HB.accent,
  blocked: HB.red,
  planned: HB.blue,
  prototype: HB.cyan || HB.blue,
  deprecated: HB.inkMute
};
var CATCOL = {
  ai: HB.purple,
  skill: HB.blue,
  connector: HB.cyan || HB.blue,
  logic: HB.purple,
  custom: HB.blue,
  output: HB.green,
  input: HB.blue,
  trigger: HB.amber,
  compose: HB.accent,
  transform: HB.amber,
  host: HB.cyan || HB.blue,
  agent: HB.accent,
  watch: HB.green,
  preview: HB.cyan || HB.blue,
  note: HB.inkMute,
  adapter: HB.amber,
  slider: HB.blue,
  rule: HB.purple,
  globals: HB.cyan || HB.blue,
  attention: HB.accent
};
var catCol = function catCol(c) {
  return CATCOL[c] || HB.inkMute;
};
var DETAIL_W = 1650; // viewBox width below which domains auto-resolve to nodes

// every node is a micro-domain: a detailed internal pipeline. Generated
// deterministically from category when not explicitly authored, so it's never empty.
var PIPE_ARCHE = {
  ai: ['prompt assemble', 'context inject', 'model call', 'stream parse', 'validate', 'emit'],
  skill: ['trigger', 'gather inputs', 'plan steps', 'execute', 'verify', 'write back'],
  connector: ['handshake', 'auth', 'open channel', 'marshal', 'heartbeat', 'reconnect'],
  logic: ['receive', 'evaluate rules', 'branch', 'transform', 'emit'],
  compose: ['collect', 'layout', 'render', 'paginate', 'export'],
  transform: ['parse', 'normalize', 'map', 'serialize'],
  input: ['capture', 'sanitize', 'normalize', 'publish'],
  output: ['subscribe', 'format', 'deliver', 'ack'],
  host: ['discover', 'bind', 'session', 'dispatch'],
  trigger: ['listen', 'debounce', 'match', 'fire'],
  custom: ['input', 'process', 'output'],
  note: ['note']
};
var PSTAGE_COL = {
  "in": HB.blue,
  process: HB.purple,
  out: HB.green
};

// Every wire carries a typed SIGNAL = the canonical port type from the app's node
// grammar (stem-core.jsx DATA_TYPES). Same vocabulary as the in-app session canvas,
// so what's wired here is wired there. Category → its emitted data-type.
var SIGNAL = {
  ai: 'completion',
  skill: 'intent',
  connector: 'record',
  logic: 'boolean',
  compose: 'document',
  transform: 'object',
  input: 'string',
  output: 'any',
  host: 'host',
  trigger: 'exec',
  agent: 'intent',
  watch: 'view',
  preview: 'view',
  custom: 'any',
  note: 'any',
  adapter: 'any',
  slider: 'number',
  rule: 'boolean',
  globals: 'object',
  attention: 'number'
};
var sigOf = function sigOf(n) {
  return n ? SIGNAL[n.cat] || 'any' : 'any';
};
var typeOf = sigOf;
// type → colour (stem-core WIRE/typeCol families)
var TYPECOL = {
  any: HB.inkMute,
  string: HB.cyan || HB.blue,
  number: HB.blue,
  "boolean": HB.amber,
  object: HB.purple,
  list: HB.purple,
  record: HB.accent,
  file: HB.green,
  view: HB.cyan || HB.blue,
  intent: HB.purple,
  completion: HB.purple,
  document: HB.accent,
  host: HB.cyan || HB.blue,
  exec: HB.ink,
  trigger: HB.amber,
  image: HB.accent,
  event: HB.amber
};
var typeColOf = function typeColOf(t) {
  return TYPECOL[t] || HB.inkMute;
};
// graph.py validate_v2: identical types pass; ANY bridges anything; else needs an Adapter.
var archCanConnect = function archCanConnect(s, d) {
  return s === d || s === 'any' || d === 'any';
};

// a node's ports = typed in/out sockets, reflected from its wiring
function nodePorts(M, id) {
  var ins = [],
    outs = [];
  M.wires.forEach(function (w) {
    if (w.b === id) {
      var s = M.nodes.find(function (n) {
        return n.id === w.a;
      });
      if (s) ins.push({
        peer: s,
        why: w.why,
        sig: sigOf(s)
      });
    }
    if (w.a === id) {
      var t = M.nodes.find(function (n) {
        return n.id === w.b;
      });
      if (t) outs.push({
        peer: t,
        why: w.why,
        sig: sigOf(t)
      });
    }
  });
  return {
    ins: ins,
    outs: outs
  };
}
function nodePipeline(n) {
  if (n.pipeline && n.pipeline.length) return n.pipeline;
  var arche = PIPE_ARCHE[n.cat] || PIPE_ARCHE.custom;
  return arche.map(function (t, i) {
    return {
      id: n.id + '_s' + i,
      t: t,
      role: i === 0 ? 'in' : i === arche.length - 1 ? 'out' : 'process',
      status: i === 0 ? 'live' : i < arche.length - 1 ? n.status === 'vision' ? 'vision' : 'partial' : n.status
    };
  });
}
var MapCanvas = React.forwardRef(function MapCanvas(props, ref) {
  var M = props.M,
    vis = props.vis,
    sel = props.sel,
    selMode = props.selMode,
    expanded = props.expanded,
    openNodes = props.openNodes,
    agentsByNode = props.agentsByNode,
    activeWires = props.activeWires,
    onSelect = props.onSelect,
    onSelectBox = props.onSelectBox,
    onMarquee = props.onMarquee,
    onMove = props.onMove,
    onMoveDomain = props.onMoveDomain,
    onToggleDomain = props.onToggleDomain,
    onToggleNode = props.onToggleNode,
    onInspect = props.onInspect,
    onNodeContext = props.onNodeContext,
    onConnect = props.onConnect,
    onWireContext = props.onWireContext,
    query = props.query;
  var svgRef = React.useRef(null);
  var worldRef = React.useRef(null); // wrapper <g>: carries the live pan transform
  // FULL BOX — the extent "frame all" fits. Domains sitting OFF the published layout grid
  // are excluded from the FRAMING only (they still render, exactly where they are). One
  // off-cell box used to inflate the frame from 2610 to 3707 wide — a ~21% shrink of the
  // whole map that undid the label legibility work. The test is exact against M.grid, not
  // statistical, so there is no threshold to tune and nothing is silently rewritten.
  var layout = React.useMemo(function () {
    var ds = M.domains;
    if (!ds.length) return {
      box: {
        x: 0,
        y: 0,
        w: 1000,
        h: 800
      },
      outliers: []
    };
    var g = M.grid;
    var aligned = function aligned(d) {
      if (!g) return true;
      var rx = Math.abs((d.x - g.x0) % g.px),
        ry = Math.abs((d.y - g.y0) % g.py);
      return Math.min(rx, g.px - rx) <= 2 && Math.min(ry, g.py - ry) <= 2;
    };
    // cell coords, then keep only the contiguous run of occupied rows/cols containing the
    // MODE row/col — a domain across an empty gap is off-grid even if perfectly aligned.
    var cell = function cell(d) {
      return {
        c: Math.round((d.x - g.x0) / g.px),
        r: Math.round((d.y - g.y0) / g.py)
      };
    };
    var run = function run(vals) {
      var cnt = {};
      vals.forEach(function (v) {
        return cnt[v] = (cnt[v] || 0) + 1;
      });
      var occ = Object.keys(cnt).map(Number).sort(function (a, b) {
        return a - b;
      });
      var mode = occ.reduce(function (m, v) {
        return cnt[v] > cnt[m] ? v : m;
      }, occ[0]);
      var lo = mode,
        hi = mode;
      while (occ.indexOf(lo - 1) >= 0) lo--;
      while (occ.indexOf(hi + 1) >= 0) hi++;
      return {
        lo: lo,
        hi: hi
      };
    };
    var keep = ds.filter(aligned);
    if (g && keep.length) {
      var cs = keep.map(function (d) {
        return cell(d);
      });
      var R = run(cs.map(function (c) {
          return c.r;
        })),
        C = run(cs.map(function (c) {
          return c.c;
        }));
      keep = keep.filter(function (d) {
        var c = cell(d);
        return c.r >= R.lo && c.r <= R.hi && c.c >= C.lo && c.c <= C.hi;
      });
    }
    if (keep.length < Math.max(2, Math.ceil(ds.length * 0.5))) keep = ds;
    var xs = keep.map(function (d) {
        return d.x;
      }),
      ys = keep.map(function (d) {
        return d.y;
      });
    var xe = keep.map(function (d) {
        return d.x + d.w;
      }),
      ye = keep.map(function (d) {
        return d.y + d.h;
      });
    var x0 = Math.min.apply(Math, _toConsumableArray(xs)),
      y0 = Math.min.apply(Math, _toConsumableArray(ys));
    return {
      box: {
        x: x0 - 60,
        y: y0 - 60,
        w: Math.max.apply(Math, _toConsumableArray(xe)) - x0 + 120,
        h: Math.max.apply(Math, _toConsumableArray(ye)) - y0 + 120
      },
      outliers: ds.filter(function (d) {
        return keep.indexOf(d) < 0;
      }).map(function (d) {
        return d.key;
      })
    };
  }, [M.domains, M.grid]);
  var fullBox = layout.box;
  var offGridKey = layout.outliers.join('|');
  React.useEffect(function () {
    if (props.onOffGrid) props.onOffGrid(layout.outliers);
  }, [offGridKey]);
  var _React$useState = React.useState(fullBox),
    _React$useState2 = _slicedToArray(_React$useState, 2),
    vb = _React$useState2[0],
    setVb = _React$useState2[1];
  var vbRef = React.useRef(vb);
  vbRef.current = vb;
  var raf = React.useRef(null);
  var drag = React.useRef(null);
  var _React$useState3 = React.useState(null),
    _React$useState4 = _slicedToArray(_React$useState3, 2),
    marquee = _React$useState4[0],
    setMarquee = _React$useState4[1];
  var _React$useState5 = React.useState(null),
    _React$useState6 = _slicedToArray(_React$useState5, 2),
    wire = _React$useState6[0],
    setWire = _React$useState6[1];
  var wireRef = React.useRef(null);
  wireRef.current = wire;
  var _React$useState7 = React.useState(null),
    _React$useState8 = _slicedToArray(_React$useState7, 2),
    hovDom = _React$useState8[0],
    setHovDom = _React$useState8[1];
  var _React$useState9 = React.useState(null),
    _React$useState0 = _slicedToArray(_React$useState9, 2),
    hovWire = _React$useState0[0],
    setHovWire = _React$useState0[1];
  var _React$useState1 = React.useState(null),
    _React$useState10 = _slicedToArray(_React$useState1, 2),
    dragDom = _React$useState10[0],
    setDragDom = _React$useState10[1];
  var dragDomRef = React.useRef(null);
  dragDomRef.current = dragDom;
  var domMovedRef = React.useRef(false);
  var off = function off(dom) {
    return dragDom && dragDom.key === dom ? dragDom : {
      dx: 0,
      dy: 0
    };
  };

  // cached canvas rect — refreshed by the ResizeObserver below, not per pointer event
  var rectRef = React.useRef(null);
  var rect = function rect() {
    return rectRef.current || (svgRef.current ? rectRef.current = svgRef.current.getBoundingClientRect() : {
      left: 0,
      top: 0,
      width: 1000,
      height: 800
    });
  };
  var _React$useState11 = React.useState(0),
    _React$useState12 = _slicedToArray(_React$useState11, 2),
    pxW = _React$useState12[0],
    setPxW = _React$useState12[1];
  React.useEffect(function () {
    // SELF-HEALING SIZE SIGNAL. This effect used to bail permanently when svgRef.current was
    // null on its single pass, and it only observed the <svg> itself — so a flex sibling
    // changing width produced NO re-render, the label attributes kept whatever size the last
    // render computed, and every screen-size floor appeared broken while actually never being
    // recomputed. It now never early-returns: it (re)attaches its observer whenever the ref
    // appears, watches the parent box too, and polls as a floor. pxW exists only to tell React
    // that geometry moved; the size maths reads the painted transform.
    var last = 0,
      ro = null,
      seen = null;
    var _read = function read() {
      var el = svgRef.current;
      if (!el) return;
      if (el !== seen) {
        // ref appeared or swapped — (re)subscribe
        seen = el;
        if (ro) ro.disconnect();
        ro = new ResizeObserver(_read);
        ro.observe(el);
        if (el.parentElement) ro.observe(el.parentElement);
      }
      var r = el.getBoundingClientRect();
      rectRef.current = r;
      var w = r.width || 0;
      if (!w || Math.abs(w - last) < 2) return;
      last = w;
      setPxW(w);
    };
    _read();
    window.addEventListener('resize', _read);
    var poll = setInterval(_read, 400);
    var inval = function inval() {
      rectRef.current = null;
    };
    window.addEventListener('scroll', inval, true);
    return function () {
      window.removeEventListener('resize', _read);
      clearInterval(poll);
      if (ro) ro.disconnect();
      window.removeEventListener('scroll', inval, true);
    };
  }, []);
  // ── VIEWBOX TRANSPORT ──
  // The map is ~1400 SVG elements (204 node cards, 397 wire bundles, 794 sockets). Routing
  // every pan/zoom frame through React state re-rendered that whole tree per frame, which
  // is what made the motion stutter. During MOTION we write the viewBox straight to the DOM
  // — zero React work, the browser just re-rasterises — and commit to state once the
  // gesture settles, so everything derived from vb (label scaling, macro thresholds)
  // updates on a single render at the end.
  var pushVB = function pushVB(v) {
    vbRef.current = v;
    var el = svgRef.current;
    if (el) el.setAttribute('viewBox', "".concat(v.x, " ").concat(v.y, " ").concat(v.w, " ").concat(v.h));
  };
  var commitTO = React.useRef(null);
  var commitVB = function commitVB() {
    var delay = arguments.length > 0 && arguments[0] !== undefined ? arguments[0] : 0;
    clearTimeout(commitTO.current);
    commitTO.current = setTimeout(function () {
      return setVb(_objectSpread({}, vbRef.current));
    }, delay);
  };
  var setVB = function setVB(v) {
    pushVB(v);
    commitVB(0);
  };

  // Eased pan/zoom. Driven by rAF; falls back to a timer running the SAME ease if the frame
  // loop is starved (embedded/background frames) — so the motion stays smooth there instead
  // of snapping straight to the destination.
  var animFb = React.useRef(null);
  var animateTo = function animateTo(t) {
    var ms = arguments.length > 1 && arguments[1] !== undefined ? arguments[1] : 460;
    cancelAnimationFrame(raf.current);
    clearInterval(animFb.current);
    var from = _objectSpread({}, vbRef.current),
      t0 = performance.now();
    var ease = function ease(x) {
      return 1 - Math.pow(1 - x, 3);
    };
    var at = function at(now) {
      var p = Math.min(1, (now - t0) / ms),
        e = ease(p);
      pushVB({
        x: from.x + (t.x - from.x) * e,
        y: from.y + (t.y - from.y) * e,
        w: from.w + (t.w - from.w) * e,
        h: from.h + (t.h - from.h) * e
      });
      if (p >= 1) {
        cancelAnimationFrame(raf.current);
        clearInterval(animFb.current);
        commitVB(0);
        return true;
      }
      return false;
    };
    var rafAlive = false;
    var _step = function step(now) {
      rafAlive = true;
      if (!at(now)) raf.current = requestAnimationFrame(_step);
    };
    raf.current = requestAnimationFrame(_step);
    setTimeout(function () {
      if (!rafAlive) animFb.current = setInterval(function () {
        return at(performance.now());
      }, 16);
    }, 80);
  };
  var aspect = function aspect() {
    var r = rect();
    return r.height / r.width;
  };
  // FRAME — fits a world box inside the canvas SAFE AREA, not the raw viewport: the
  // masthead, scale ladder, hint bar and command bar float over the map, so centering
  // blindly buries the first and last rows under them.
  // Insets measured against the floating chrome: masthead + scale ladder above, hint bar +
  // command bar below. Content is fitted INSIDE this rect, never under the overlays.
  var SAFE = {
    t: 92,
    b: 84,
    l: 22,
    r: 22
  };
  var frame = function frame(x, y, w, h) {
    var pad = arguments.length > 4 && arguments[4] !== undefined ? arguments[4] : 0.03;
    var r = rect();
    var W = r.width || 1000,
      H = r.height || 800;
    var px = w * pad,
      py = h * pad;
    var tx = x - px,
      ty = y - py,
      tw = w + px * 2,
      th = h + py * 2;
    var availW = Math.max(80, W - SAFE.l - SAFE.r),
      availH = Math.max(80, H - SAFE.t - SAFE.b);
    var k = Math.min(availW / tw, availH / th); // px per world unit
    var nw = W / k,
      nh = H / k;
    // centre the target inside the safe rect, then back out to the full viewBox
    var offX = SAFE.l + (availW - tw * k) / 2,
      offY = SAFE.t + (availH - th * k) / 2;
    animateTo({
      x: tx - offX / k,
      y: ty - offY / k,
      w: nw,
      h: nh
    });
  };
  React.useImperativeHandle(ref, function () {
    return {
      fitAll: function fitAll() {
        return frame(fullBox.x, fullBox.y, fullBox.w, fullBox.h, 0.02);
      },
      focusDomain: function focusDomain(key) {
        var d = M.domains.find(function (x) {
          return x.key === key;
        });
        if (d) frame(d.x - 20, d.y - 20, d.w + 40, d.h + 40, 0.06);
      },
      focusNode: function focusNode(id) {
        var n = M.nodes.find(function (x) {
          return x.id === id;
        });
        if (n) frame(n.x - 280, n.y - 200, NW + 560, NHt + 400, 0.04);
      },
      zoomTo: function zoomTo(w) {
        var c = {
          x: vbRef.current.x + vbRef.current.w / 2,
          y: vbRef.current.y + vbRef.current.h / 2
        };
        var nh = w * aspect();
        animateTo({
          x: c.x - w / 2,
          y: c.y - nh / 2,
          w: w,
          h: nh
        });
      }
    };
  });
  React.useEffect(function () {
    var t = setTimeout(function () {
      return frame(fullBox.x, fullBox.y, fullBox.w, fullBox.h, 0.02);
    }, 60);
    return function () {
      return clearTimeout(t);
    };
  }, []);

  // published so the shell can resolve a library DROP point into world coordinates
  React.useEffect(function () {
    window.__atlasToWorld = function (cx, cy) {
      return toWorld(cx, cy);
    };
    return function () {
      delete window.__atlasToWorld;
    };
  }, []);
  var toWorld = function toWorld(cx, cy) {
    var r = rect();
    return {
      x: vbRef.current.x + (cx - r.left) / r.width * vbRef.current.w,
      y: vbRef.current.y + (cy - r.top) / r.height * vbRef.current.h
    };
  };
  var onWheel = function onWheel(e) {
    e.preventDefault();
    var w = toWorld(e.clientX, e.clientY);
    var f = e.deltaY < 0 ? 0.85 : 1.18;
    var r = rect();
    var nw = Math.min(fullBox.w * 1.3, Math.max(360, vbRef.current.w * f));
    var nh = nw * (r.height / r.width);
    cancelAnimationFrame(raf.current);
    clearInterval(animFb.current);
    var t = {
      x: w.x - (w.x - vbRef.current.x) * (nw / vbRef.current.w),
      y: w.y - (w.y - vbRef.current.y) * (nh / vbRef.current.h),
      w: nw,
      h: nh
    };
    perFrame(function () {
      return pushVB(t);
    });
    commitVB(140);
  };
  var onDown = function onDown(e) {
    if (e.target.closest('.atlas-node') || e.target.closest('.dom-head')) return;
    if (selMode || e.shiftKey) {
      var w = toWorld(e.clientX, e.clientY);
      drag.current = {
        mode: 'marquee',
        sx: w.x,
        sy: w.y,
        additive: e.shiftKey
      };
      setMarquee({
        x: w.x,
        y: w.y,
        w: 0,
        h: 0
      });
    } else {
      drag.current = {
        mode: 'pan',
        sx: e.clientX,
        sy: e.clientY,
        vb0: _objectSpread({}, vbRef.current)
      };
      if (!e.metaKey) onSelect(null, false);
    }
  };
  // one state update per animation frame, no matter how many mousemoves arrive
  var coalesce = React.useRef({
    raf: 0,
    timer: 0,
    fn: null
  });
  // Coalesce to one update per frame, but NEVER depend on rAF alone: in a throttled or
  // background frame rAF may never fire, and since every pan and zoom routes through here that
  // silently froze the viewBox — the map could not be moved or zoomed at all, which also left
  // the node-card zoom gate with no way out. A timer races the frame callback; whichever
  // arrives first runs the work and cancels the other.
  var perFrame = function perFrame(fn) {
    coalesce.current.fn = fn;
    if (coalesce.current.raf || coalesce.current.timer) return;
    var run = function run() {
      if (coalesce.current.raf) {
        cancelAnimationFrame(coalesce.current.raf);
        coalesce.current.raf = 0;
      }
      if (coalesce.current.timer) {
        clearTimeout(coalesce.current.timer);
        coalesce.current.timer = 0;
      }
      var f = coalesce.current.fn;
      coalesce.current.fn = null;
      if (f) f();
    };
    coalesce.current.raf = requestAnimationFrame(run);
    coalesce.current.timer = setTimeout(run, 24);
  };
  var onMoveBg = function onMoveBg(e) {
    if (!drag.current) return;
    var r = rect();
    if (drag.current.mode === 'pan') {
      var dx = (e.clientX - drag.current.sx) / r.width * drag.current.vb0.w,
        dy = (e.clientY - drag.current.sy) / r.height * drag.current.vb0.h;
      drag.current.dx = dx;
      drag.current.dy = dy;
      if (worldRef.current) worldRef.current.setAttribute('transform', "translate(".concat(dx, " ").concat(dy, ")"));
    } else if (drag.current.mode === 'marquee') {
      var w = toWorld(e.clientX, e.clientY);
      perFrame(function () {
        return setMarquee({
          x: Math.min(w.x, drag.current.sx),
          y: Math.min(w.y, drag.current.sy),
          w: Math.abs(w.x - drag.current.sx),
          h: Math.abs(w.y - drag.current.sy)
        });
      });
    } else if (drag.current.mode === 'node') {
      var _w = toWorld(e.clientX, e.clientY);
      drag.current.moved = drag.current.moved || Math.abs(e.clientX - drag.current.sx) + Math.abs(e.clientY - drag.current.sy) > 3;
      var nx = _w.x - drag.current.off.x,
        ny = _w.y - drag.current.off.y;
      drag.current.el.setAttribute('transform', "translate(".concat(nx, ",").concat(ny, ")"));
      drag.current.last = {
        x: nx,
        y: ny
      };
    } else if (drag.current.mode === 'domain') {
      var _w2 = toWorld(e.clientX, e.clientY);
      var _dx = _w2.x - drag.current.ox,
        _dy = _w2.y - drag.current.oy;
      if (Math.abs(_dx) + Math.abs(_dy) > 4) {
        drag.current.moved = true;
        domMovedRef.current = true;
      }
      perFrame(function () {
        return setDragDom({
          key: drag.current && drag.current.key,
          dx: _dx,
          dy: _dy
        });
      });
    } else if (drag.current.mode === 'wire') {
      var _w3 = toWorld(e.clientX, e.clientY);
      perFrame(function () {
        return setWire({
          from: drag.current && drag.current.from,
          x: _w3.x,
          y: _w3.y
        });
      });
    }
  };
  var onUp = function onUp() {
    if (!drag.current) return;
    if (drag.current.mode === 'marquee' && marquee) {
      var r = marquee;
      var hit = function hit(x, y, w, h) {
        return x + w > r.x && x < r.x + r.w && y + h > r.y && y < r.y + r.h;
      };
      // open domains → grab their nodes; collapsed domains → grab the domain itself (one gesture, every scale)
      var ids = M.nodes.filter(function (n) {
        return domOpen(n.dom) && hit(n.x, n.y, NW, NHt);
      }).map(function (n) {
        return n.id;
      });
      var domKeys = M.domains.filter(function (d) {
        return !domOpen(d.key) && hit(d.x, d.y, d.w, d.h);
      }).map(function (d) {
        return d.key;
      });
      if (onMarquee) onMarquee(ids, domKeys, drag.current.additive);else onSelectBox(ids, drag.current.additive);
      setMarquee(null);
    }
    if (drag.current.mode === 'pan') {
      var d = drag.current,
        g = worldRef.current;
      if (d.dx || d.dy) pushVB(_objectSpread(_objectSpread({}, vbRef.current), {}, {
        x: d.vb0.x - d.dx,
        y: d.vb0.y - d.dy
      }));
      if (g) g.removeAttribute('transform');
      commitVB(0); // one render after the gesture, not per frame
    }
    if (drag.current.mode === 'node' && drag.current.moved && drag.current.last) onMove(drag.current.id, drag.current.last.x, drag.current.last.y);
    if (drag.current.mode === 'domain') {
      var dd = dragDomRef.current;
      if (drag.current.moved && dd) onMoveDomain(drag.current.key, dd.dx, dd.dy);
      setDragDom(null);
    }
    if (drag.current.mode === 'wire') {
      var wp = wireRef.current;
      if (wp) {
        var t = M.nodes.filter(function (n) {
          return visN(n) && domOpen(n.dom);
        }).find(function (n) {
          var o = off(n.dom);
          var x = n.x + o.dx,
            y = n.y + o.dy;
          var w = openNodes.has(n.id) ? Math.max(NW, 56 + nodePipeline(n).length * 104) : NW;
          var h = openNodes.has(n.id) ? 150 : NHt;
          return wp.x >= x && wp.x <= x + w && wp.y >= y && wp.y <= y + h;
        });
        if (t && t.id !== drag.current.from) onConnect && onConnect(drag.current.from, t.id);
      }
      setWire(null);
    }
    drag.current = null;
  };
  React.useEffect(function () {
    return function () {
      cancelAnimationFrame(raf.current);
      clearInterval(animFb.current);
      clearTimeout(commitTO.current);
    };
  }, []);
  React.useEffect(function () {
    window.addEventListener('mousemove', onMoveBg);
    window.addEventListener('mouseup', onUp);
    return function () {
      window.removeEventListener('mousemove', onMoveBg);
      window.removeEventListener('mouseup', onUp);
    };
  });
  var nodeDown = function nodeDown(e, n) {
    if (selMode || n.frozen) return;
    e.stopPropagation();
    var w = toWorld(e.clientX, e.clientY);
    drag.current = {
      mode: 'node',
      id: n.id,
      sx: e.clientX,
      sy: e.clientY,
      off: {
        x: w.x - n.x,
        y: w.y - n.y
      },
      el: e.currentTarget,
      moved: false
    };
  };
  var startWire = function startWire(e, n) {
    e.stopPropagation();
    var w = toWorld(e.clientX, e.clientY);
    drag.current = {
      mode: 'wire',
      from: n.id
    };
    setWire({
      from: n.id,
      x: w.x,
      y: w.y
    });
  };
  var nodeCtx = function nodeCtx(e, n) {
    e.preventDefault();
    e.stopPropagation();
    onNodeContext && onNodeContext(n.id, e.clientX, e.clientY);
  };
  var domDown = function domDown(e, d) {
    if (e.shiftKey) {
      e.stopPropagation();
      return;
    }
    if (selMode) return;
    e.stopPropagation();
    var w = toWorld(e.clientX, e.clientY);
    domMovedRef.current = false;
    drag.current = {
      mode: 'domain',
      key: d.key,
      ox: w.x,
      oy: w.y,
      moved: false
    };
  };

  // ── LOD: a domain resolves to nodes when zoomed in OR force-expanded; collapses when force-collapsed ──
  var autoDetail = vb.w < DETAIL_W;
  var domOpen = function domOpen(key) {
    if (expanded.collapsed.has(key)) return false;
    if (expanded.open.has(key)) return true;
    return autoDetail;
  };
  // open domains hug their member nodes (so dragging a node reshapes the domain); collapsed use authored box
  // mass = members + external wiring; normalised 0..1 across the model
  var domMass = React.useMemo(function () {
    var memb = {},
      deg = {};
    M.domains.forEach(function (d) {
      memb[d.key] = 0;
      deg[d.key] = 0;
    });
    M.nodes.forEach(function (n) {
      if (memb[n.dom] != null) memb[n.dom]++;
    });
    var domOfN = {};
    M.nodes.forEach(function (n) {
      return domOfN[n.id] = n.dom;
    });
    M.wires.forEach(function (w) {
      var a = domOfN[w.a],
        b = domOfN[w.b];
      if (a && b && a !== b) {
        if (deg[a] != null) deg[a]++;
        if (deg[b] != null) deg[b]++;
      }
    });
    var raw = {};
    M.domains.forEach(function (d) {
      return raw[d.key] = memb[d.key] + deg[d.key] * 0.8;
    });
    var vals = Object.values(raw);
    var lo = Math.min.apply(Math, vals),
      hi = Math.max.apply(Math, vals);
    var out = {};
    M.domains.forEach(function (d) {
      return out[d.key] = hi > lo ? (raw[d.key] - lo) / (hi - lo) : 0.5;
    });
    return {
      t: out,
      members: memb,
      degree: deg
    };
  }, [M.domains, M.nodes, M.wires]);
  var domBounds = function domBounds(d) {
    if (!domOpen(d.key)) {
      // 0.62 → 1.0 of the authored cell: the lightest domain reads as clearly smaller than
      // the heaviest, without any box shrinking so far that its title stops fitting.
      var k = 0.78 + 0.22 * (domMass.t[d.key] != null ? domMass.t[d.key] : 0.5);
      var w = Math.round(d.w * k),
        h = Math.round(d.h * k);
      // centred in its cell so the grid rhythm survives
      return {
        x: d.x + Math.round((d.w - w) / 2),
        y: d.y + Math.round((d.h - h) / 2),
        w: w,
        h: h
      };
    }
    var ms = M.nodes.filter(function (n) {
      return n.dom === d.key;
    });
    if (!ms.length) return {
      x: d.x,
      y: d.y,
      w: d.w,
      h: d.h
    };
    var x0 = Infinity,
      y0 = Infinity,
      x1 = -Infinity,
      y1 = -Infinity;
    ms.forEach(function (n) {
      var w = openNodes.has(n.id) ? Math.max(NW, 56 + nodePipeline(n).length * 104) : NW;
      var h = openNodes.has(n.id) ? 150 : NHt;
      x0 = Math.min(x0, n.x);
      y0 = Math.min(y0, n.y);
      x1 = Math.max(x1, n.x + w);
      y1 = Math.max(y1, n.y + h);
    });
    var padX = 26,
      padT = 56,
      padB = 26;
    return {
      x: x0 - padX,
      y: y0 - padT,
      w: x1 - x0 + padX * 2,
      h: y1 - y0 + padT + padB
    };
  };
  var domCenter = function domCenter(d) {
    var b = domBounds(d);
    return {
      x: b.x + b.w / 2,
      y: b.y + b.h / 2
    };
  };
  var nodeAnchor = function nodeAnchor(id) {
    var n = M.nodes.find(function (x) {
      return x.id === id;
    });
    if (!n) return null;
    var o = off(n.dom);
    if (domOpen(n.dom)) return {
      x: n.x + NW / 2 + o.dx,
      y: n.y + NHt / 2 + o.dy
    };
    var d = M.domains.find(function (x) {
      return x.key === n.dom;
    });
    return d ? {
      x: domCenter(d).x + o.dx,
      y: domCenter(d).y + o.dy
    } : null;
  };
  var domOf = React.useMemo(function () {
    var o = {};
    M.nodes.forEach(function (n) {
      return o[n.id] = n.dom;
    });
    return o;
  }, [M]);
  var nodeById = React.useMemo(function () {
    var m = {};
    M.nodes.forEach(function (n) {
      return m[n.id] = n;
    });
    return m;
  }, [M]);
  // typed port index: every node's in/out sockets, reflected from the wire graph (computed once)
  var portIndex = React.useMemo(function () {
    var idx = {};
    M.nodes.forEach(function (n) {
      return idx[n.id] = {
        ins: [],
        outs: []
      };
    });
    M.wires.forEach(function (w) {
      var a = nodeById[w.a],
        b = nodeById[w.b];
      if (!a || !b || a.id === b.id) return;
      var t = w.t || sigOf(a);
      idx[a.id].outs.push({
        peer: b,
        why: w.why,
        sig: t
      });
      idx[b.id].ins.push({
        peer: a,
        why: w.why,
        sig: t
      });
    });
    // DECLARED ports: params the user promoted, fields added, triggers — wireable knobs with no peer yet
    M.nodes.forEach(function (n) {
      var dp = n.ports || {};
      (dp.ins || []).forEach(function (p) {
        return idx[n.id] && idx[n.id].ins.push({
          declared: true,
          label: p.id,
          sig: p.t || 'any'
        });
      });
      (dp.outs || []).forEach(function (p) {
        return idx[n.id] && idx[n.id].outs.push({
          declared: true,
          label: p.id,
          sig: p.t || 'any'
        });
      });
    });
    return idx;
  }, [M, nodeById]);
  // domain interface: roll-up of member nodes' cross-domain ports, grouped by peer domain (a reflection)
  var domIface = React.useMemo(function () {
    var out = {};
    M.domains.forEach(function (d) {
      return out[d.key] = {
        inb: {},
        outb: {}
      };
    });
    M.wires.forEach(function (w) {
      var a = nodeById[w.a],
        b = nodeById[w.b];
      if (!a || !b || a.dom === b.dom) return;
      if (out[a.dom]) out[a.dom].outb[b.dom] = (out[a.dom].outb[b.dom] || 0) + 1;
      if (out[b.dom]) out[b.dom].inb[a.dom] = (out[b.dom].inb[a.dom] || 0) + 1;
    });
    return out;
  }, [M, nodeById]);
  var visN = function visN(n) {
    return vis.domains.has(n.dom) && vis.status.has(n.status) && (!query || ((n.title || '') + (n.sub || '')).toLowerCase().includes(query.toLowerCase()));
  };

  // ── wires: BUNDLED & WEIGHTED. Endpoints resolve to node (open) or domain centre
  // (collapsed); wires sharing the same pair collapse into one weighted edge. ──
  var endpoint = function endpoint(id) {
    var n = M.nodes.find(function (x) {
      return x.id === id;
    });
    if (!n) return null;
    var o = off(n.dom);
    if (domOpen(n.dom)) {
      var isO = openNodes.has(id);
      var w = isO ? Math.max(NW, 56 + nodePipeline(n).length * 104) : NW;
      var h = isO ? 150 : NHt;
      return {
        key: 'n:' + id,
        x: n.x + w / 2 + o.dx,
        y: n.y + h / 2 + o.dy,
        dom: n.dom,
        box: {
          x: n.x + o.dx,
          y: n.y + o.dy,
          w: w,
          h: h
        }
      };
    }
    var d = M.domains.find(function (x) {
      return x.key === n.dom;
    });
    if (!d) return null;
    var c = domCenter(d);
    return {
      key: 'd:' + n.dom,
      x: c.x + o.dx,
      y: c.y + o.dy,
      dom: n.dom
    };
  };
  // clip a wire endpoint to the node-card boundary so wires meet edges, not centers
  var trimToBox = function trimToBox(box, toward) {
    var cx = box.x + box.w / 2,
      cy = box.y + box.h / 2;
    var dx = toward.x - cx,
      dy = toward.y - cy;
    if (!dx && !dy) return {
      x: cx,
      y: cy
    };
    var t = Math.min((box.w / 2 + 3) / (Math.abs(dx) || 1e-6), (box.h / 2 + 3) / (Math.abs(dy) || 1e-6));
    return {
      x: cx + dx * t,
      y: cy + dy * t
    };
  };
  // KNOB MAP — ONE authority for every collapsed domain's boundary sockets. Both the knob
  // render and the wire resolver read from this, so a wire always lands ON its socket.
  // (Previously each computed its own top-6 slice, so any peer past the 6th fell back to
  // the box centre and the wire visibly missed the knob.) Every wired peer gets a socket;
  // spacing compresses to fit the box rather than truncating the list.
  var knobMap = React.useMemo(function () {
    var out = {};
    M.domains.forEach(function (d) {
      if (domOpen(d.key)) return;
      var iface = domIface[d.key];
      if (!iface) return;
      var bb = domBounds(d);
      var mk = function mk(entries, side) {
        var list = entries.filter(function (_ref) {
          var _ref2 = _slicedToArray(_ref, 1),
            k = _ref2[0];
          return vis.domains.has(k) && k !== d.key;
        }).sort(function (a, b2) {
          return b2[1] - a[1];
        });
        var n = list.length;
        if (!n) return;
        var span = Math.max(0, bb.h - 150);
        var gap = n > 1 ? Math.min(34, span / (n - 1)) : 0;
        list.forEach(function (_ref3, i) {
          var _ref4 = _slicedToArray(_ref3, 2),
            pk = _ref4[0],
            ct = _ref4[1];
          out[d.key] = out[d.key] || {};
          out[d.key][pk] = {
            x: side === 'L' ? bb.x : bb.x + bb.w,
            y: bb.y + bb.h / 2 + (i - (n - 1) / 2) * gap,
            side: side,
            ct: ct,
            peer: pk,
            gap: gap
          };
        });
      };
      // a peer appears on ONE side only — outbound wins, so a bidirectional pair gets a
      // single socket instead of two that both claim the same wire.
      var outE = Object.entries(iface.outb);
      var outKeys = new Set(outE.map(function (_ref5) {
        var _ref6 = _slicedToArray(_ref5, 1),
          k = _ref6[0];
        return k;
      }));
      mk(outE, 'R');
      mk(Object.entries(iface.inb).filter(function (_ref7) {
        var _ref8 = _slicedToArray(_ref7, 1),
          k = _ref8[0];
        return !outKeys.has(k);
      }), 'L');
    });
    return out;
  }, [M, domIface, vis.domains, expanded, openNodes]);

  // NODE SOCKET MAP — the same single-authority rule as knobMap, one level down. Positions
  // are LOCAL to the node origin; both the port render and the wire resolver read them, so
  // a node-level wire terminates exactly on its socket instead of on an arbitrary point of
  // the card boundary. Every wired peer gets a socket (spacing compresses to fit) — the old
  // 5-port cap silently orphaned the rest.
  var nodeSock = React.useMemo(function () {
    var out = {};
    M.nodes.forEach(function (n) {
      var pp = portIndex[n.id];
      if (!pp) return;
      var isO = openNodes.has(n.id);
      var w = isO ? Math.max(NW, 56 + nodePipeline(n).length * 104) : NW;
      var h = isO ? 150 : NHt;
      var rec = {
        ins: {},
        outs: {},
        list: [],
        w: w,
        h: h
      };
      var rail = function rail(arr, edgeX, side) {
        var cnt = arr.length;
        if (!cnt) return;
        var span = Math.max(0, h - 24);
        var gap = cnt > 1 ? Math.min(11, span / (cnt - 1)) : 0;
        arr.forEach(function (p, i) {
          var s = {
            lx: edgeX,
            ly: h / 2 + (i - (cnt - 1) / 2) * gap,
            side: side,
            port: p,
            sig: p.sig
          };
          rec.list.push(s);
          if (p.peer) rec[side === 'in' ? 'ins' : 'outs'][p.peer.id] = s;
        });
      };
      rail(pp.ins, 0, 'in');
      rail(pp.outs, w, 'out');
      out[n.id] = rec;
    });
    return out;
  }, [M, portIndex, openNodes]);

  // world position of a node's socket facing a given peer (open domains only)
  var nodePortPos = function nodePortPos(id, peerId, prefer) {
    var n = nodeById[id];
    if (!n || !domOpen(n.dom)) return null;
    var rec = nodeSock[id];
    if (!rec) return null;
    var s = prefer === 'out' ? rec.outs[peerId] || rec.ins[peerId] : rec.ins[peerId] || rec.outs[peerId];
    if (!s) return null;
    var o = off(n.dom);
    return {
      x: n.x + s.lx + o.dx,
      y: n.y + s.ly + o.dy,
      side: s.side === 'in' ? 'L' : 'R',
      sock: true
    };
  };

  // resolve a COLLAPSED domain's boundary socket toward a given peer domain.
  var domPortPos = function domPortPos(domKey, peerKey) {
    var d = M.domains.find(function (x) {
      return x.key === domKey;
    });
    if (!d || domOpen(domKey)) return null;
    var k = knobMap[domKey] && knobMap[domKey][peerKey];
    if (!k) return null;
    var o = off(domKey);
    return {
      x: k.x + o.dx,
      y: k.y + o.dy,
      knob: true
    };
  };
  var domCol = function domCol(k) {
    return (M.domains.find(function (d) {
      return d.key === k;
    }) || {}).col || HB.inkMute;
  };
  // Filled by the domain map, emitted after the wire layer — see "DOMAIN IDENTITY" below.
  // upp/scr/cardFs are defined BEFORE the eager wire render below (it calls cardFs at build time).
  // SCREEN-CONSTANT TYPE — the whole model is ~2700×3000 world units, so at "fit all" a
  // 20px world label renders at ~5px and the map turns into unreadable confetti. Domain
  // identity (title, count, tally) is chrome, not geometry: it keeps a fixed SCREEN size
  // by scaling with world-units-per-pixel (observed, not measured mid-render), clamped so
  // it never dwarfs its own box.
  // Measure the element LIVE rather than trusting the pxW state mirror: pxW is only a
  // re-render trigger, and if its observer subscription goes stale the mirror silently keeps
  // the mount-time width — which made every screen floor below compute against 808px while
  // the map was actually 420px, dragging domain titles to 6px. The live rect is the truth at
  // paint time; pxW stays purely as the signal that tells React to re-render.
  // WORLD UNITS PER SCREEN PIXEL — read from the RENDERED transform, not from state.
  // The viewBox is written imperatively to the DOM by pushVB during pan/zoom without a state
  // update, so the `vb` state and the real viewBox routinely diverge; dividing the STATE width
  // by the live pixel width therefore under-reported the zoom-out and silently collapsed every
  // screen-size floor below (domain titles rendered at 7px on a narrow map). getScreenCTM().a
  // is the actual world→screen scale the browser is painting with, so it cannot disagree with
  // what the user sees. vbRef (the imperative source of truth) is the fallback, never `vb`.
  var upp = function () {
    var el = svgRef.current;
    if (el && el.getScreenCTM) {
      var m = el.getScreenCTM();
      if (m && m.a) return 1 / m.a;
    }
    // hostW is a change-signal, not a measurement — always measure the element itself.
    var w = el && el.getBoundingClientRect().width || props.hostW || pxW;
    var src = vbRef.current || vb;
    return w ? src.w / w : 1;
  }();
  var scr = function scr(px, maxWorld) {
    return Math.min(maxWorld == null ? Infinity : maxWorld, px * Math.max(1, upp));
  };
  var macro = upp > 1.9; // zoomed out far enough that node-level detail is noise
  var cardFs = function cardFs(px) {
    return Math.max(9 * upp, px * Math.max(1, upp * 0.55));
  };
  var domChrome = [];
  var wireEls = vis.wires ? function () {
    var bundles = {};
    M.wires.forEach(function (w) {
      var da = domOf[w.a],
        db = domOf[w.b];
      if (!da || !db) return;
      if (!vis.domains.has(da) || !vis.domains.has(db)) return;
      var A = endpoint(w.a),
        B = endpoint(w.b);
      if (!A || !B || A.key === B.key) return;
      var k = [A.key, B.key].sort().join('|');
      if (!bundles[k]) bundles[k] = {
        A: A,
        B: B,
        wt: 0,
        da: da,
        db: db,
        rel: false,
        ia: w.a,
        ib: w.b
      };
      bundles[k].wt++;
      if (sel.nodes.has(w.a) || sel.nodes.has(w.b)) bundles[k].rel = true;
    });
    var labelOf = function labelOf(bd) {
      var nm = function nm(id) {
        var n = nodeById[id];
        if (n) return n.title;
        var d = M.domains.find(function (x) {
          return x.key === id;
        });
        return d ? d.title : id;
      };
      var an = bd.da !== bd.db ? (M.domains.find(function (x) {
        return x.key === bd.da;
      }) || {}).title : nm(bd.ia);
      var bn = bd.da !== bd.db ? (M.domains.find(function (x) {
        return x.key === bd.db;
      }) || {}).title : nm(bd.ib);
      return (an || bd.da) + ' → ' + (bn || bd.db);
    };
    return Object.entries(bundles).map(function (_ref9) {
      var _ref0 = _slicedToArray(_ref9, 2),
        k = _ref0[0],
        bd = _ref0[1];
      var A = bd.A,
        B = bd.B,
        wt = bd.wt;
      var cross = bd.da !== bd.db;
      var rel = bd.rel;
      var hovW = hovWire === k,
        selW = sel.wire && sel.wire.key === k;
      var hot = hovDom && (bd.da === hovDom || bd.db === hovDom);
      var nodeWire = A.box && B.box; // both endpoints resolved to node cards — a real zoomed-in relation
      // MACRO LEGIBILITY: 72 cross-domain bundles at full weight reads as spaghetti. At rest
      // the inter-domain layer is a quiet substrate; hovering a domain or selecting a node
      // brings ITS relations forward. Node-level wires (zoomed in) always draw at full weight.
      var quiet = cross && !nodeWire && !rel && !hot;
      var col = rel ? HB.accent : hot ? domCol(hovDom) : domCol(bd.da);
      var sw = rel ? 3.4 : quiet ? Math.min(2.6, 0.9 + Math.log2(wt + 1) * 0.55) : Math.min(8, 1.9 + Math.log2(wt + 1) * (cross ? 1.6 : 1.0));
      var pa = A.box ? null : domPortPos(bd.da, bd.db);
      var pb = B.box ? null : domPortPos(bd.db, bd.da);
      // node-level: terminate on the actual typed socket, not the card boundary
      var sa = A.box ? nodePortPos(bd.ia, bd.ib, 'out') : null;
      var sb = B.box ? nodePortPos(bd.ib, bd.ia, 'in') : null;
      var a0 = sa || (A.box ? trimToBox(A.box, B) : pa || A);
      var b0 = sb || (B.box ? trimToBox(B.box, A) : pb || B);
      var knobbed = !!(pa || pb || sa || sb);
      var op = selW ? 1 : hovW ? 0.95 : rel ? 0.97 : hovDom ? hot ? 0.95 : 0.06 : sel.nodes.size ? 0.05 : quiet ? 0.3 : nodeWire ? 0.72 : 0.6;
      // Socket-terminated wires leave the boundary HORIZONTALLY, like a node editor — a
      // cubic whose control points sit outboard of each socket. Reads as plugged in.
      var dpath = function () {
        if (knobbed) {
          var dx = Math.max(nodeWire ? 26 : 60, Math.abs(b0.x - a0.x) * 0.42);
          var e1 = sa || pa,
            e2 = sb || pb;
          var s1 = e1 && e1.side === 'L' ? -1 : e1 ? 1 : a0.x > b0.x ? -1 : 1;
          var s2 = e2 && e2.side === 'L' ? -1 : e2 ? 1 : b0.x > a0.x ? -1 : 1;
          return "M".concat(a0.x, ",").concat(a0.y, " C").concat(a0.x + dx * s1, ",").concat(a0.y, " ").concat(b0.x + dx * s2, ",").concat(b0.y, " ").concat(b0.x, ",").concat(b0.y);
        }
        var mx = (a0.x + b0.x) / 2,
          my = (a0.y + b0.y) / 2 + (cross && !nodeWire ? -34 : 0);
        return "M".concat(a0.x, ",").concat(a0.y, " Q").concat(mx, ",").concat(my, " ").concat(b0.x, ",").concat(b0.y);
      }();
      var mx = (a0.x + b0.x) / 2,
        my = (a0.y + b0.y) / 2 + (cross && !nodeWire && !knobbed ? -34 : 0);
      var ang = Math.atan2(b0.y - a0.y, b0.x - a0.x);
      var ah = Math.max(5, Math.min(9, sw + 2));
      return /*#__PURE__*/React.createElement("g", {
        key: k,
        style: {
          transition: 'opacity .15s'
        }
      }, op > 0.3 && !quiet && /*#__PURE__*/React.createElement("path", {
        d: dpath,
        fill: "none",
        stroke: col,
        strokeWidth: sw + 3,
        opacity: op * 0.18,
        strokeLinecap: "round"
      }), /*#__PURE__*/React.createElement("path", {
        d: dpath,
        fill: "none",
        stroke: selW ? HB.accent : col,
        strokeWidth: selW ? sw + 2.2 : hovW ? sw + 1.4 : sw,
        opacity: selW ? 1 : hovW ? Math.max(op, 0.9) : op,
        strokeLinecap: "round"
      }), /*#__PURE__*/React.createElement("path", {
        d: dpath,
        fill: "none",
        stroke: "transparent",
        strokeWidth: Math.max(13, sw + 11),
        strokeLinecap: "round",
        style: {
          pointerEvents: 'stroke',
          cursor: 'pointer'
        },
        onMouseEnter: function onMouseEnter() {
          return setHovWire(k);
        },
        onMouseLeave: function onMouseLeave() {
          return setHovWire(null);
        },
        onClick: function onClick(ev) {
          ev.stopPropagation();
          props.onPickWire && props.onPickWire({
            key: k,
            a: bd.ia,
            b: bd.ib,
            da: bd.da,
            db: bd.db,
            wt: wt,
            cross: cross
          });
        },
        onContextMenu: function onContextMenu(ev) {
          ev.preventDefault();
          ev.stopPropagation();
          props.onWireContext && props.onWireContext(bd.ia, bd.ib, ev.clientX, ev.clientY, {
            key: k,
            wt: wt,
            da: bd.da,
            db: bd.db
          });
        }
      }, /*#__PURE__*/React.createElement("title", null, labelOf(bd) + ' · ' + wt + (wt > 1 ? ' wires' : ' wire'))), selW && /*#__PURE__*/React.createElement("text", {
        x: mx,
        y: my - (sw + 9),
        fontSize: Math.max(cardFs(11), sw * 3.4),
        fontFamily: HB.mono,
        fontWeight: "700",
        textAnchor: "middle",
        fill: HB.accent
      }, labelOf(bd)), nodeWire && op > 0.2 && !knobbed && /*#__PURE__*/React.createElement("path", {
        d: "M".concat(b0.x - Math.cos(ang) * ah - Math.cos(ang - 0.5) * ah, ",").concat(b0.y - Math.sin(ang) * ah - Math.sin(ang - 0.5) * ah, " L").concat(b0.x - Math.cos(ang) * ah, ",").concat(b0.y - Math.sin(ang) * ah, " L").concat(b0.x - Math.cos(ang) * ah - Math.cos(ang + 0.5) * ah, ",").concat(b0.y - Math.sin(ang) * ah - Math.sin(ang + 0.5) * ah),
        fill: "none",
        stroke: col,
        strokeWidth: Math.max(1.4, sw * 0.7),
        opacity: op
      }), cross && !nodeWire && wt > 1 && hot && /*#__PURE__*/React.createElement("text", {
        x: mx,
        y: my - 4,
        fontSize: cardFs(11),
        fontFamily: HB.mono,
        fontWeight: "700",
        textAnchor: "middle",
        fill: col,
        opacity: 0.95
      }, wt));
    });
  }() : null;

  // ONE authority for header type: the title's real size, and where the header block ends.
  // Both the readout and the badge derive from these, so a short title (which sizes up to the
  // height cap rather than the width cap) can never run into the line beneath it.
  var titleSize = function titleSize(d, b) {
    return Math.max(12 * upp, Math.min(scr(15), b.h * 0.115));
  };
  // ellipsize to the box: the cap limits how many CHARACTERS are drawn, not how big they are
  var fitTitle = function fitTitle(d, b, fsz) {
    var t = String(d.title || '');
    // 22 left inset + the right-aligned readout's gutter. Keep the reserve tight and the
    // per-character factor honest (serif mixed case ≈ 0.44em) so a title keeps as much of its
    // meaning as the box allows — "Canvas & Grap…" tells you far more than "Canvas…".
    var avail = b.w - 22 - Math.max(52, scr(38, 120));
    var max = Math.floor(avail / Math.max(0.001, fsz * 0.44));
    if (max >= t.length) return t;
    if (max < 2) return '';
    return t.slice(0, max - 1).replace(/[\s&,·]+$/, '') + "\u2026";
  };
  var headerBottom = function headerBottom(d, b) {
    return b.y + 26 + titleSize(d, b) * 1.5;
  };
  var rollup = function rollup(ns) {
    var s = {};
    ns.forEach(function (n) {
      return s[n.status] = (s[n.status] || 0) + 1;
    });
    return s;
  };
  var cardLegible = function cardLegible() {
    return NW / upp >= 90;
  };
  // status tally: floored to 9px on screen, drawn only if that size still fits the column
  var tallyPitch = function tallyPitch(b) {
    var avail = b.w - 60;
    var cols = Math.max(1, Math.floor(avail / 104));
    return avail / cols;
  };
  var tallyFs = function tallyFs(b) {
    return Math.max(9 * upp, Math.min(13, tallyPitch(b) * 0.13));
  };
  var tallyFit = function tallyFit(b) {
    return tallyFs(b) <= tallyPitch(b) * 0.2;
  }; // is a node card wide enough to carry text?
  var fitStr = function fitStr(str, availWorld, fsz) {
    var t = String(str || '');
    var max = Math.floor(availWorld / Math.max(0.001, fsz * 0.44));
    if (max >= t.length) return t;
    if (max < 2) return '';
    return t.slice(0, max - 1).replace(/[\s:·,&]+$/, '') + "\u2026";
  };

  // ── active run flow: animated pulse along wires currently carrying a run ──
  var flowEls = activeWires && activeWires.size ? _toConsumableArray(activeWires).map(function (key) {
    var _key$split = key.split('>'),
      _key$split2 = _slicedToArray(_key$split, 2),
      a = _key$split2[0],
      b = _key$split2[1];
    var A = endpoint(a),
      B = endpoint(b);
    if (!A || !B) return null;
    var mx = (A.x + B.x) / 2,
      my = (A.y + B.y) / 2;
    return /*#__PURE__*/React.createElement("g", {
      key: 'flow' + key
    }, /*#__PURE__*/React.createElement("path", {
      d: "M".concat(A.x, ",").concat(A.y, " Q").concat(mx, ",").concat(my, " ").concat(B.x, ",").concat(B.y),
      fill: "none",
      stroke: HB.accent,
      strokeWidth: 2.6,
      opacity: 0.9,
      className: "rt-flow"
    }), /*#__PURE__*/React.createElement("circle", {
      r: 4,
      fill: HB.accent
    }, /*#__PURE__*/React.createElement("animateMotion", {
      dur: "0.9s",
      repeatCount: "indefinite",
      path: "M".concat(A.x, ",").concat(A.y, " Q").concat(mx, ",").concat(my, " ").concat(B.x, ",").concat(B.y)
    })));
  }) : null;
  return /*#__PURE__*/React.createElement("svg", {
    ref: svgRef,
    viewBox: "".concat(vb.x, " ").concat(vb.y, " ").concat(vb.w, " ").concat(vb.h),
    onMouseDown: onDown,
    onWheel: onWheel,
    style: {
      width: '100%',
      height: '100%',
      display: 'block',
      cursor: selMode ? 'crosshair' : drag.current && drag.current.mode === 'pan' ? 'grabbing' : 'grab'
    }
  }, /*#__PURE__*/React.createElement("g", {
    ref: worldRef
  }, function () {
    // A field encloses domains AND other fields, so its boundary is computed RECURSIVELY
    // and its padding grows with tier — a tier-3 boundary visibly contains the tier-2 one
    // inside it. Depth is unbounded: this walks whatever the founder built.
    var byId = {};
    (M.fields || []).forEach(function (f) {
      return byId[f.id] = f;
    });
    var _depthOf = function depthOf(id, seen) {
      var f = byId[id];
      if (!f) return 0;
      var g = seen || new Set();
      if (g.has(id)) return 0;
      g.add(id);
      var k = (f.fieldIds || []).map(function (x) {
        return _depthOf(x, g);
      });
      return 1 + (k.length ? Math.max.apply(Math, _toConsumableArray(k)) : 0);
    };
    var _boundsOf = function boundsOf(id, seen) {
      var f = byId[id];
      if (!f) return null;
      var g = seen || new Set();
      if (g.has(id)) return null;
      g.add(id);
      var x0 = Infinity,
        y0 = Infinity,
        x1 = -Infinity,
        y1 = -Infinity,
        any = false;
      M.domains.filter(function (d) {
        return (f.domKeys || []).includes(d.key) && vis.domains.has(d.key);
      }).forEach(function (d) {
        var o = off(d.key),
          b = domBounds(d);
        any = true;
        x0 = Math.min(x0, b.x + o.dx);
        y0 = Math.min(y0, b.y + o.dy);
        x1 = Math.max(x1, b.x + b.w + o.dx);
        y1 = Math.max(y1, b.y + b.h + o.dy);
      });
      (f.fieldIds || []).forEach(function (k) {
        var cb = _boundsOf(k, g);
        if (cb) {
          any = true;
          x0 = Math.min(x0, cb.x0);
          y0 = Math.min(y0, cb.y0);
          x1 = Math.max(x1, cb.x1);
          y1 = Math.max(y1, cb.y1);
        }
      });
      return any ? {
        x0: x0,
        y0: y0,
        x1: x1,
        y1: y1
      } : null;
    };
    // deepest first, so an outer tier paints behind the tiers it contains
    var ordered = _toConsumableArray(M.fields || []).sort(function (a, b) {
      return _depthOf(b.id) - _depthOf(a.id);
    });
    return ordered.map(function (f) {
      var bb = _boundsOf(f.id);
      if (!bb) return null;
      var tier = _depthOf(f.id);
      var pad = 30 + tier * 22,
        tabH = 26 + tier * 3;
      var bx = bb.x0 - pad,
        by = bb.y0 - pad - tabH,
        bw = bb.x1 - bb.x0 + pad * 2,
        bh = bb.y1 - bb.y0 + pad * 2 + tabH;
      var selF = sel.field === f.id || sel.fields && sel.fields.has(f.id);
      var col = f.col || HB.blue;
      var SUP = ['', '', '²', '³', '⁴', '⁵', '⁶', '⁷', '⁸', '⁹'];
      var sup = tier > 1 ? SUP[tier] != null ? SUP[tier] : '^' + tier : '';
      var label = "FIELD".concat(sup, " \xB7 ").concat((f.title || '').toUpperCase());
      var members = (f.domKeys || []).length + (f.fieldIds || []).length;
      return /*#__PURE__*/React.createElement("g", {
        key: f.id
      }, /*#__PURE__*/React.createElement("rect", {
        x: bx,
        y: by,
        width: bw,
        height: bh,
        rx: 26 + tier * 6,
        fill: col + (tier > 1 ? '14' : '0d'),
        stroke: selF ? col : col + 'b0',
        strokeWidth: selF ? 3 : 2,
        strokeDasharray: tier > 1 ? '22 10' : '14 9',
        style: {
          pointerEvents: 'none',
          filter: "drop-shadow(0 0 8px ".concat(col, "44)")
        }
      }), /*#__PURE__*/React.createElement("g", {
        style: {
          cursor: 'pointer'
        },
        onClick: function onClick(e) {
          e.stopPropagation();
          props.onPickField && props.onPickField(f.id, e.shiftKey || e.metaKey);
        },
        onContextMenu: function onContextMenu(e) {
          e.preventDefault();
          e.stopPropagation();
          props.onFieldContext && props.onFieldContext(f.id, e.clientX, e.clientY);
        }
      }, /*#__PURE__*/React.createElement("rect", {
        x: bx + 20,
        y: by,
        width: Math.max(196, label.length * 8.4 + 82),
        height: tabH,
        rx: 9,
        fill: col
      }), /*#__PURE__*/React.createElement("text", {
        x: bx + 36,
        y: by + tabH * 0.68,
        fontSize: cardFs(12.5),
        fontFamily: HB.mono,
        fontWeight: "700",
        letterSpacing: "0.14em",
        fill: window.AH && window.AH.onFill || "#180f08"
      }, "\u2B21 ", label), /*#__PURE__*/React.createElement("text", {
        x: bx + Math.max(196, label.length * 8.4 + 82) + 4,
        y: by + tabH * 0.68,
        fontSize: cardFs(10),
        fontFamily: HB.mono,
        fill: col
      }, members)));
    });
  }(), M.domains.filter(function (d) {
    return vis.domains.has(d.key);
  }).map(function (d) {
    var open = domOpen(d.key);
    var ms = M.nodes.filter(function (n) {
      return n.dom === d.key;
    });
    var st = rollup(ms);
    var isSelDom = sel.domain === d.key || sel.domains && sel.domains.has(d.key);
    var o = off(d.key);
    var b = domBounds(d);
    return /*#__PURE__*/React.createElement("g", {
      key: d.key,
      transform: "translate(".concat(o.dx, ",").concat(o.dy, ")"),
      onMouseEnter: function onMouseEnter() {
        return setHovDom(d.key);
      },
      onMouseLeave: function onMouseLeave() {
        return setHovDom(null);
      },
      onContextMenu: function onContextMenu(e) {
        e.preventDefault();
        e.stopPropagation();
        props.onDomainContext && props.onDomainContext(d.key, e.clientX, e.clientY);
      }
    }, /*#__PURE__*/React.createElement("rect", {
      x: b.x,
      y: b.y,
      width: b.w,
      height: b.h,
      rx: 18,
      fill: open ? HB.paper2 : HB.card,
      stroke: isSelDom || hovDom === d.key ? d.col : HB.line,
      strokeWidth: isSelDom ? 2.4 : 1.4,
      strokeDasharray: d.grouped ? '9 6' : undefined,
      opacity: open ? 0.6 : 1,
      style: {
        filter: open ? 'none' : 'drop-shadow(0 5px 16px rgba(0,0,0,.1))',
        transition: 'none'
      }
    }), d.grouped && /*#__PURE__*/React.createElement("text", {
      x: b.x + b.w - 20,
      y: b.y + 26 + titleSize(d, b) * 0.78,
      fontSize: Math.max(9 * upp, Math.min(scr(8), b.h * 0.036)),
      fontFamily: HB.mono,
      letterSpacing: "0.16em",
      textAnchor: "end",
      fill: d.col,
      opacity: 0.8,
      style: {
        pointerEvents: 'none'
      }
    }, "\u229E GROUPED"), /*#__PURE__*/React.createElement("rect", {
      x: b.x,
      y: b.y,
      width: 6,
      height: b.h,
      rx: 3,
      fill: d.col,
      opacity: 0.85
    }), domChrome.push(/*#__PURE__*/React.createElement("g", {
      key: 'hd' + d.key,
      transform: "translate(".concat(o.dx, ",").concat(o.dy, ")"),
      onMouseEnter: function onMouseEnter() {
        return setHovDom(d.key);
      },
      onMouseLeave: function onMouseLeave() {
        return setHovDom(null);
      },
      onContextMenu: function onContextMenu(e) {
        e.preventDefault();
        e.stopPropagation();
        props.onDomainContext && props.onDomainContext(d.key, e.clientX, e.clientY);
      }
    }, /*#__PURE__*/React.createElement("g", {
      className: "dom-head",
      style: {
        cursor: dragDom && dragDom.key === d.key ? 'grabbing' : 'grab'
      },
      onMouseDown: function onMouseDown(e) {
        return domDown(e, d);
      },
      onClick: function onClick(e) {
        e.stopPropagation();
        if (domMovedRef.current) {
          domMovedRef.current = false;
          return;
        }
        if (e.shiftKey || e.metaKey || e.ctrlKey) {
          props.onPickDomain && props.onPickDomain(d.key, true);
          return;
        }
        onToggleDomain(d.key, !open);
        props.onPickDomain && props.onPickDomain(d.key);
      }
    }, /*#__PURE__*/React.createElement("rect", {
      x: b.x + 10,
      y: b.y + 10,
      width: b.w - 20,
      height: Math.max(34, scr(30, 90)),
      rx: 8,
      fill: "transparent"
    }), function () {
      var fsz = titleSize(d, b);
      return /*#__PURE__*/React.createElement("text", {
        x: b.x + 22,
        y: b.y + 26 + fsz * 0.78,
        fontSize: fsz,
        fontWeight: "700",
        fontFamily: HB.serif,
        fill: d.col
      }, /*#__PURE__*/React.createElement("title", null, d.title), fitTitle(d, b, fsz));
    }(), function () {
      var fsz = Math.max(11 * upp, Math.min(scr(10.5), b.h * 0.062));
      return /*#__PURE__*/React.createElement("text", {
        x: b.x + 22,
        y: headerBottom(d, b) + fsz * 0.86,
        fontSize: fsz,
        fontFamily: HB.mono,
        fill: HB.inkSoft
      }, (d.params || []).length ? '⚙ ' + (d.params || []).length + ' · ' : '', ms.length, " capabilities \xB7 ", open ? '▾' : '▸');
    }()))) && null, !open && domChrome.push(/*#__PURE__*/React.createElement("g", {
      key: 'sm' + d.key,
      transform: "translate(".concat(o.dx, ",").concat(o.dy, ")")
    }, function () {
      var blocked = st.blocked || 0;
      var vision = st.vision || 0;
      var live = st.live || 0;
      var risk = blocked > 0 ? 'blocked' : vision / (ms.length || 1) > 0.5 ? 'vision' : live / (ms.length || 1) > 0.4 ? 'live' : null;
      var riskCol = risk === 'blocked' ? HB.red : risk === 'vision' ? HB.accent : risk === 'live' ? HB.green : null;
      return /*#__PURE__*/React.createElement("g", {
        style: {
          pointerEvents: 'none'
        }
      }, riskCol && /*#__PURE__*/React.createElement("rect", {
        x: b.x,
        y: b.y,
        width: b.w,
        height: b.h,
        rx: 18,
        fill: "none",
        stroke: riskCol,
        strokeWidth: 2.4,
        opacity: 0.85
      }), blocked > 0 && /*#__PURE__*/React.createElement("g", {
        transform: "translate(".concat(b.x + b.w - 30, ",").concat(b.y + 18, ")")
      }, /*#__PURE__*/React.createElement("circle", {
        r: scr(7, 30),
        fill: HB.red
      }), /*#__PURE__*/React.createElement("text", {
        y: scr(3.5, 14),
        fontSize: scr(9, 42),
        fontWeight: "700",
        fontFamily: HB.mono,
        textAnchor: "middle",
        fill: window.AH && window.AH.onFill || "#180f08"
      }, blocked)), function () {
        // ONE headline per card, sized from the box so it cannot collide: the
        // dominant status. The raw count already reads in the header line, so a
        // giant duplicate numeral was both redundant and the worst overflow.
        var top = Object.entries(st).sort(function (a, c) {
          return c[1] - a[1];
        })[0];
        if (!top) return null;
        var fsz = Math.min(b.h * 0.16, b.w * 0.1);
        var sub = Math.max(10 * upp, fsz * 0.28);
        return /*#__PURE__*/React.createElement("g", null, /*#__PURE__*/React.createElement("text", {
          x: b.x + b.w / 2,
          y: b.y + b.h * 0.56,
          fontSize: fsz,
          fontWeight: "700",
          fontFamily: HB.serif,
          textAnchor: "middle",
          fill: STC[top[0]] || d.col,
          opacity: 0.95
        }, top[1]), /*#__PURE__*/React.createElement("text", {
          x: b.x + b.w / 2,
          y: b.y + b.h * 0.56 + fsz * 0.34 + sub * 1.5,
          fontSize: sub,
          fontFamily: HB.mono,
          letterSpacing: "0.12em",
          textAnchor: "middle",
          fill: HB.inkSoft
        }, String(top[0]).toUpperCase()));
      }(), tallyFit(b) && /*#__PURE__*/React.createElement("g", {
        transform: "translate(".concat(b.x + 30, ",").concat(b.y + b.h - 60, ")")
      }, /*#__PURE__*/React.createElement("rect", {
        width: b.w - 60,
        height: 12,
        rx: 6,
        fill: HB.paper
      }), function () {
        var acc = 0;
        var tot = ms.length || 1;
        return Object.entries(st).map(function (_ref1) {
          var _ref10 = _slicedToArray(_ref1, 2),
            s = _ref10[0],
            n = _ref10[1];
          var w = (b.w - 60) * n / tot;
          var seg = /*#__PURE__*/React.createElement("rect", {
            key: s,
            x: acc,
            width: w,
            height: 12,
            fill: STC[s]
          });
          acc += w;
          return seg;
        });
      }()), tallyFit(b) && function () {
        var avail = b.w - 60;
        var entries = Object.entries(st);
        var cols = Math.max(1, Math.min(entries.length, Math.floor(avail / 104)));
        var pitch = avail / cols;
        var fs = tallyFs(b);
        return /*#__PURE__*/React.createElement("g", {
          transform: "translate(".concat(b.x + 30, ",").concat(b.y + b.h - 36, ")")
        }, entries.slice(0, cols).map(function (_ref11, i) {
          var _ref12 = _slicedToArray(_ref11, 2),
            s = _ref12[0],
            c = _ref12[1];
          return /*#__PURE__*/React.createElement("g", {
            key: s,
            transform: "translate(".concat(i * pitch, ",0)")
          }, /*#__PURE__*/React.createElement("rect", {
            width: fs * 0.75,
            height: fs * 0.75,
            rx: 2,
            y: 2,
            fill: STC[s]
          }), /*#__PURE__*/React.createElement("text", {
            x: fs * 1.15,
            y: fs * 0.85,
            fontSize: fs,
            fontFamily: HB.mono,
            fill: HB.inkSoft
          }, c, " ", s));
        }), entries.length > cols && /*#__PURE__*/React.createElement("text", {
          x: avail,
          y: fs * 0.85,
          fontSize: fs,
          fontFamily: HB.mono,
          textAnchor: "end",
          fill: HB.inkDim
        }, "+", entries.length - cols));
      }());
    }())) && null, !open && function () {
      var ks = knobMap[d.key];
      if (!ks) return null;
      var entries = Object.values(ks);
      var hovK = hovDom && hovDom !== d.key ? hovDom : null;
      return /*#__PURE__*/React.createElement("g", {
        style: {
          pointerEvents: 'none'
        }
      }, entries.map(function (k) {
        var pc = (M.domains.find(function (x) {
          return x.key === k.peer;
        }) || {}).col || HB.inkMute;
        var lit = !hovK || k.peer === hovK;
        var lx = k.x + (k.side === 'L' ? scr(11, 50) : -scr(11, 50));
        return /*#__PURE__*/React.createElement("g", {
          key: k.side + k.peer,
          opacity: lit ? 1 : 0.18
        }, /*#__PURE__*/React.createElement("circle", {
          cx: k.x,
          cy: k.y,
          r: scr(4.6, 20),
          fill: HB.paper,
          stroke: pc,
          strokeWidth: scr(1.7, 7)
        }), /*#__PURE__*/React.createElement("circle", {
          cx: k.x,
          cy: k.y,
          r: scr(1.8, 8),
          fill: pc
        }), (!macro || lit) && function () {
          var fsz = Math.min(scr(8.5), (k.gap || 34) * 0.62);
          // the socket-gap cap can drive this to ~5px, which reads as speckle rather
          // than a number — below 9px on screen the dot alone carries the connection
          if (fsz / upp < 9) return null;
          return /*#__PURE__*/React.createElement("text", {
            x: lx,
            y: k.y + fsz * 0.36,
            fontSize: fsz,
            fontFamily: HB.mono,
            fontWeight: "700",
            textAnchor: k.side === 'L' ? 'start' : 'end',
            fill: pc,
            opacity: 0.9
          }, k.ct);
        }());
      }), entries.some(function (k) {
        return k.side === 'L';
      }) && /*#__PURE__*/React.createElement("text", {
        x: b.x + 13,
        y: b.y + 62,
        fontSize: cardFs(8),
        fontFamily: HB.mono,
        letterSpacing: "0.12em",
        fill: HB.blue
      }, "\u25B8 IN"), entries.some(function (k) {
        return k.side === 'R';
      }) && /*#__PURE__*/React.createElement("text", {
        x: b.x + b.w - 13,
        y: b.y + 62,
        fontSize: cardFs(8),
        fontFamily: HB.mono,
        letterSpacing: "0.12em",
        textAnchor: "end",
        fill: HB.green
      }, "OUT \u25B8"));
    }());
  }), /*#__PURE__*/React.createElement("g", null, wireEls), /*#__PURE__*/React.createElement("g", null, flowEls), /*#__PURE__*/React.createElement("g", null, domChrome), M.nodes.filter(function (n) {
    return visN(n) && domOpen(n.dom);
  }).map(function (n) {
    var isSel = sel.nodes.has(n.id);
    var ags = agentsByNode[n.id] || [];
    var o = off(n.dom);
    var isOpen = openNodes.has(n.id);
    if (isOpen) {
      var pipe = nodePipeline(n);
      var PW = Math.max(NW, 56 + pipe.length * 104),
        PH = 150;
      return /*#__PURE__*/React.createElement("g", {
        key: n.id,
        className: "atlas-node",
        transform: "translate(".concat(n.x + o.dx, ",").concat(n.y + o.dy, ")"),
        style: {
          cursor: 'pointer'
        },
        onMouseDown: function onMouseDown(e) {
          return nodeDown(e, n);
        },
        onClick: function onClick(e) {
          e.stopPropagation();
          onSelect(n.id, e.shiftKey || e.metaKey);
        },
        onContextMenu: function onContextMenu(e) {
          return nodeCtx(e, n);
        },
        onDoubleClick: function onDoubleClick(e) {
          e.stopPropagation();
          onToggleNode(n.id, false);
        }
      }, isSel && /*#__PURE__*/React.createElement("rect", {
        x: -4,
        y: -4,
        width: PW + 8,
        height: PH + 8,
        rx: 13,
        fill: "none",
        stroke: HB.accent,
        strokeWidth: 2.5,
        strokeDasharray: "5 4"
      }), /*#__PURE__*/React.createElement("rect", {
        width: PW,
        height: PH,
        rx: 12,
        fill: HB.paper2,
        stroke: isSel ? HB.accent : catCol(n.cat),
        strokeWidth: isSel ? 2 : 1.4,
        style: {
          filter: 'drop-shadow(0 10px 24px rgba(0,0,0,.16))'
        }
      }), /*#__PURE__*/React.createElement("rect", {
        x: 0,
        y: 10,
        width: 4,
        height: PH - 20,
        rx: 2,
        fill: STC[n.status] || HB.inkMute
      }), function () {
        var fCat = cardFs(7.5),
          fTitle = cardFs(13),
          fCnt = cardFs(9);
        var avail = PW - 130; // leave the right-aligned stage count its gutter
        return /*#__PURE__*/React.createElement("g", null, /*#__PURE__*/React.createElement("text", {
          x: 14,
          y: 22,
          fontSize: fCat,
          fontFamily: HB.mono,
          letterSpacing: "0.14em",
          fill: catCol(n.cat)
        }, fitStr((n.cat || '').toUpperCase() + ' · PIPELINE', avail, fCat)), /*#__PURE__*/React.createElement("text", {
          x: 14,
          y: 40,
          fontSize: fTitle,
          fontWeight: "700",
          fontFamily: HB.sans,
          fill: HB.ink
        }, /*#__PURE__*/React.createElement("title", null, n.title), fitStr(n.title, avail, fTitle)), /*#__PURE__*/React.createElement("text", {
          x: PW - 14,
          y: 24,
          fontSize: fCnt,
          fontFamily: HB.mono,
          textAnchor: "end",
          fill: HB.inkMute
        }, pipe.length, " stages \u25BE"));
      }(), function () {
        var rec = nodeSock[n.id];
        if (!rec) return null;
        var sigs = function sigs(side) {
          var seen = [];
          rec.list.filter(function (s) {
            return s.side === side;
          }).forEach(function (s) {
            if (!seen.includes(s.sig)) seen.push(s.sig);
          });
          return seen;
        };
        var cnt = function cnt(side) {
          return rec.list.filter(function (s) {
            return s.side === side;
          }).length;
        };
        var summary = function summary(x, side, col) {
          var c = cnt(side === 'L' ? 'in' : 'out');
          if (!c) return null;
          return /*#__PURE__*/React.createElement("g", {
            style: {
              pointerEvents: 'none'
            }
          }, /*#__PURE__*/React.createElement("text", {
            x: side === 'L' ? x + 11 : x - 11,
            y: PH - 26,
            fontSize: cardFs(7.5),
            fontFamily: HB.mono,
            fontWeight: "700",
            textAnchor: side === 'L' ? 'start' : 'end',
            fill: col
          }, side === 'L' ? "\u25B8 IN " : "OUT \u25B8 ", c), /*#__PURE__*/React.createElement("text", {
            x: side === 'L' ? x + 11 : x - 11,
            y: PH - 15,
            fontSize: cardFs(7),
            fontFamily: HB.mono,
            textAnchor: side === 'L' ? 'start' : 'end',
            fill: HB.inkMute
          }, sigs(side === 'L' ? 'in' : 'out').slice(0, 2).join(' / ') || "\u2014"));
        };
        return /*#__PURE__*/React.createElement("g", null, rec.list.map(function (s, i) {
          var p = s.port;
          var col = typeColOf(s.sig);
          var wireable = s.side === 'out' && !n.frozen;
          return /*#__PURE__*/React.createElement("g", {
            key: s.side + i,
            style: {
              cursor: wireable ? 'crosshair' : 'pointer'
            },
            onMouseDown: function onMouseDown(e) {
              if (wireable) startWire(e, n);else e.stopPropagation();
            },
            onClick: function onClick(e) {
              e.stopPropagation();
              if (p.peer) {
                onSelect(p.peer.id, e.shiftKey || e.metaKey);
                onInspect(p.peer.id);
              }
            }
          }, /*#__PURE__*/React.createElement("title", null, (s.side === 'in' ? "\u25B8 in \xB7 " : "out \u25B8 ") + (p.peer ? p.peer.title : p.label || 'port') + " \xB7 " + s.sig), /*#__PURE__*/React.createElement("circle", {
            cx: s.lx,
            cy: s.ly,
            r: 6,
            fill: "transparent"
          }), /*#__PURE__*/React.createElement("circle", {
            cx: s.lx,
            cy: s.ly,
            r: 3.4,
            fill: p.declared ? col : HB.card,
            stroke: col,
            strokeWidth: 1.5
          }), /*#__PURE__*/React.createElement("circle", {
            cx: s.lx,
            cy: s.ly,
            r: 1.3,
            fill: p.declared ? HB.card : col
          }));
        }), summary(0, 'L', HB.blue), summary(PW, 'R', HB.green));
      }(), /*#__PURE__*/React.createElement("g", {
        transform: "translate(28,72)"
      }, pipe.map(function (s, i) {
        var x = i * 104;
        var col = PSTAGE_COL[s.role] || HB.purple;
        return /*#__PURE__*/React.createElement("g", {
          key: s.id,
          transform: "translate(".concat(x, ",0)")
        }, i > 0 && /*#__PURE__*/React.createElement("path", {
          d: "M".concat(-12, ",26 L0,26"),
          stroke: HB.inkMute,
          strokeWidth: 1.4,
          markerEnd: ""
        }), i > 0 && /*#__PURE__*/React.createElement("path", {
          d: "M".concat(-6, ",22 L0,26 L").concat(-6, ",30"),
          fill: "none",
          stroke: HB.inkMute,
          strokeWidth: 1.2
        }), /*#__PURE__*/React.createElement("rect", {
          width: 92,
          height: 52,
          rx: 8,
          fill: HB.card,
          stroke: col,
          strokeWidth: 1.2
        }), /*#__PURE__*/React.createElement("circle", {
          cx: 12,
          cy: 14,
          r: 3.5,
          fill: STC[s.status] || col
        }), 92 / upp >= 74 ? function () {
          var fRole = cardFs(7),
            fName = cardFs(9.5);
          return /*#__PURE__*/React.createElement("g", null, /*#__PURE__*/React.createElement("text", {
            x: 22,
            y: 17,
            fontSize: fRole,
            fontFamily: HB.mono,
            fill: col,
            letterSpacing: "0.06em"
          }, fitStr(s.role.toUpperCase(), 62, fRole)), /*#__PURE__*/React.createElement("text", {
            x: 12,
            y: 36,
            fontSize: fName,
            fontFamily: HB.sans,
            fontWeight: "600",
            fill: HB.ink
          }, /*#__PURE__*/React.createElement("title", null, s.t), fitStr(s.t, 70, fName)));
        }() : /*#__PURE__*/React.createElement("rect", {
          x: 12,
          y: 30,
          width: 62,
          height: 5,
          rx: 2.5,
          fill: col,
          opacity: 0.5
        }));
      })));
    }
    return /*#__PURE__*/React.createElement("g", {
      key: n.id,
      className: "atlas-node",
      transform: "translate(".concat(n.x + o.dx, ",").concat(n.y + o.dy, ")"),
      style: {
        cursor: 'pointer'
      },
      onMouseDown: function onMouseDown(e) {
        return nodeDown(e, n);
      },
      onClick: function onClick(e) {
        e.stopPropagation();
        onSelect(n.id, e.shiftKey || e.metaKey);
      },
      onContextMenu: function onContextMenu(e) {
        return nodeCtx(e, n);
      },
      onDoubleClick: function onDoubleClick(e) {
        e.stopPropagation();
        onToggleNode(n.id, true);
        onInspect(n.id);
      }
    }, isSel && /*#__PURE__*/React.createElement("rect", {
      x: -4,
      y: -4,
      width: NW + 8,
      height: NHt + 8,
      rx: 11,
      fill: "none",
      stroke: HB.accent,
      strokeWidth: 2.5,
      strokeDasharray: "5 4"
    }), /*#__PURE__*/React.createElement("rect", {
      width: NW,
      height: NHt,
      rx: 9,
      fill: HB.card,
      stroke: n.frozen ? HB.inkMute : isSel ? HB.accent : HB.line,
      strokeWidth: isSel ? 2 : 1,
      strokeDasharray: n.frozen ? '5 3' : '0',
      style: {
        filter: isSel ? 'drop-shadow(0 8px 18px rgba(217,119,87,.28))' : 'none'
      }
    }), /*#__PURE__*/React.createElement("rect", {
      x: 0,
      y: 8,
      width: 4,
      height: NHt - 16,
      rx: 2,
      fill: STC[n.status] || HB.inkMute,
      opacity: n.frozen ? 0.5 : 1
    }), /*#__PURE__*/React.createElement("circle", {
      cx: NW - 13,
      cy: 13,
      r: 4,
      fill: STC[n.status] || HB.inkMute
    }), cardLegible() ? function () {
      var avail = NW - 24;
      var fCat = cardFs(7.5),
        fTitle = cardFs(11),
        fSub = cardFs(8),
        fParam = cardFs(7.5),
        fTag = cardFs(7.5);
      return /*#__PURE__*/React.createElement("g", null, vis.labels && /*#__PURE__*/React.createElement("text", {
        x: 12,
        y: 18,
        fontSize: fCat,
        fontFamily: HB.mono,
        letterSpacing: "0.12em",
        fill: catCol(n.cat)
      }, fitStr((n.cat || '').toUpperCase(), avail, fCat)), /*#__PURE__*/React.createElement("text", {
        x: 12,
        y: vis.labels ? 36 : 28,
        fontSize: fTitle,
        fontWeight: "700",
        fontFamily: HB.sans,
        fill: HB.ink
      }, /*#__PURE__*/React.createElement("title", null, n.title), fitStr(n.title, avail, fTitle)), /*#__PURE__*/React.createElement("text", {
        x: 12,
        y: vis.labels ? 50 : 44,
        fontSize: fSub,
        fontFamily: HB.sans,
        fill: HB.inkSoft
      }, fitStr(n.sub, avail, fSub)), vis.params && (n.params || []).slice(0, 1).map(function (p, k) {
        return /*#__PURE__*/React.createElement("text", {
          key: k,
          x: 12,
          y: 66 + k * 11,
          fontSize: fParam,
          fontFamily: HB.mono,
          fill: HB.inkMute
        }, fitStr(p.k + ': ' + p.v, avail, fParam));
      }), /*#__PURE__*/React.createElement("text", {
        x: NW - 12,
        y: NHt - 8,
        fontSize: fTag,
        fontFamily: HB.mono,
        textAnchor: "end",
        fill: HB.inkMute,
        opacity: 0.7
      }, n.frozen ? '▣ frozen' : n.cat === 'watch' ? '◉ watcher' : '⊞ pipeline'));
    }() :
    /*#__PURE__*/
    // too small for type: the card becomes a status block, its category the only cue
    React.createElement("g", {
      style: {
        pointerEvents: 'none'
      }
    }, /*#__PURE__*/React.createElement("rect", {
      x: 10,
      y: NHt / 2 - 9,
      width: NW - 34,
      height: 5,
      rx: 2.5,
      fill: catCol(n.cat),
      opacity: 0.55
    }), /*#__PURE__*/React.createElement("rect", {
      x: 10,
      y: NHt / 2 + 1,
      width: (NW - 34) * 0.6,
      height: 5,
      rx: 2.5,
      fill: HB.line
    }), /*#__PURE__*/React.createElement("title", null, n.title)), function () {
      var rec = nodeSock[n.id];
      if (!rec || !rec.list.length) return null;
      return /*#__PURE__*/React.createElement("g", null, rec.list.map(function (s, i) {
        var p = s.port;
        var col = typeColOf(s.sig);
        var wireable = s.side === 'out' && !n.frozen;
        return /*#__PURE__*/React.createElement("g", {
          key: s.side + i,
          style: {
            cursor: wireable ? 'crosshair' : 'pointer'
          },
          onMouseDown: function onMouseDown(e) {
            if (wireable) startWire(e, n);else e.stopPropagation();
          },
          onClick: function onClick(e) {
            e.stopPropagation();
            if (p.peer) {
              onSelect(p.peer.id, e.shiftKey || e.metaKey);
              onInspect(p.peer.id);
            }
          }
        }, /*#__PURE__*/React.createElement("title", null, (s.side === 'in' ? '▸ in · ' : 'out ▸ ') + (p.peer ? p.peer.title : p.label || 'port') + ' · ' + s.sig + (p.declared ? ' · promoted' : '')), /*#__PURE__*/React.createElement("circle", {
          cx: s.lx,
          cy: s.ly,
          r: 6,
          fill: "transparent"
        }), /*#__PURE__*/React.createElement("circle", {
          cx: s.lx,
          cy: s.ly,
          r: 3.1,
          fill: p.declared ? col : HB.card,
          stroke: col,
          strokeWidth: 1.4
        }), /*#__PURE__*/React.createElement("circle", {
          cx: s.lx,
          cy: s.ly,
          r: 1.2,
          fill: p.declared ? HB.card : col
        }));
      }), /*#__PURE__*/React.createElement("g", {
        style: {
          pointerEvents: 'none'
        }
      }, cardLegible() && function () {
        var ins = rec.list.filter(function (s) {
          return s.side === 'in';
        }).length;
        var f = cardFs(6.5);
        return ins > 0 && /*#__PURE__*/React.createElement("text", {
          x: 5,
          y: NHt - 7,
          fontSize: f,
          fontFamily: HB.mono,
          fill: HB.blue,
          opacity: 0.75
        }, ins, "\u25B8");
      }()));
    }(), cardLegible() && function () {
      var rs = n.rt && n.rt.state || null;
      if (!rs || rs === 'idle') return null;
      var rc = window.RT && window.RT.RT_COL[rs] || HB.inkMute;
      return rs === 'running' ? /*#__PURE__*/React.createElement("circle", {
        cx: NW / 2,
        cy: NHt / 2,
        r: 5,
        fill: "none",
        stroke: rc,
        strokeWidth: 2,
        className: "rt-run-ring"
      }) : /*#__PURE__*/React.createElement("g", {
        transform: "translate(".concat(NW - 30, ",").concat(NHt - 17, ")")
      }, /*#__PURE__*/React.createElement("rect", {
        width: 20,
        height: 12,
        rx: 3,
        fill: rc + '22',
        stroke: rc,
        strokeWidth: "0.7"
      }), /*#__PURE__*/React.createElement("text", {
        x: 4,
        y: 9,
        fontSize: cardFs(7),
        fontFamily: HB.mono,
        fill: rc
      }, rs === 'fresh' ? '✓ ok' : rs === 'stale' ? 'stale' : 'err'));
    }(), cardLegible() && n.cat === 'watch' && function () {
      var up = (window.RT ? window.RT.upstreamIds(M, n.id) : []).map(function (i) {
        return M.nodes.find(function (x) {
          return x.id === i;
        });
      }).filter(Boolean)[0];
      var res = up && up.rt && up.rt.runs && up.rt.runs.length ? up.rt.runs[up.rt.runs.length - 1].result : window.RT ? window.RT.rtResult(up || n) : '—';
      return /*#__PURE__*/React.createElement("text", {
        x: 12,
        y: NHt - 22,
        fontSize: cardFs(8),
        fontFamily: HB.mono,
        fill: HB.green
      }, "\u25B8 ", String(res).slice(0, 22));
    }(), cardLegible() && ags.length > 0 && /*#__PURE__*/React.createElement("g", {
      transform: "translate(14,".concat(NHt - 16, ")")
    }, /*#__PURE__*/React.createElement("rect", {
      width: 20,
      height: 12,
      rx: 6,
      fill: HB.accentSoft,
      stroke: HB.accent,
      strokeWidth: "0.7"
    }), /*#__PURE__*/React.createElement("circle", {
      cx: 6,
      cy: 6,
      r: 2.2,
      fill: HB.accent
    }), /*#__PURE__*/React.createElement("text", {
      x: 11,
      y: 9,
      fontSize: cardFs(7),
      fontFamily: HB.mono,
      fill: HB.accentHi
    }, ags.length)), isSel && !n.frozen && /*#__PURE__*/React.createElement("g", null, /*#__PURE__*/React.createElement("circle", {
      cx: NW,
      cy: NHt / 2,
      r: 11,
      fill: "transparent",
      style: {
        cursor: 'crosshair'
      },
      onMouseDown: function onMouseDown(e) {
        return startWire(e, n);
      }
    }), /*#__PURE__*/React.createElement("circle", {
      cx: NW,
      cy: NHt / 2,
      r: 5.5,
      fill: HB.accent,
      stroke: HB.card,
      strokeWidth: 2,
      style: {
        cursor: 'crosshair',
        pointerEvents: 'none'
      }
    }), /*#__PURE__*/React.createElement("path", {
      d: "M".concat(NW - 2, ",").concat(NHt / 2 - 2, " L").concat(NW + 2, ",").concat(NHt / 2, " L").concat(NW - 2, ",").concat(NHt / 2 + 2),
      stroke: HB.card,
      strokeWidth: 1.2,
      fill: "none",
      style: {
        pointerEvents: 'none'
      }
    })), isSel && /*#__PURE__*/React.createElement("circle", {
      cx: 0,
      cy: NHt / 2,
      r: 4,
      fill: HB.card,
      stroke: HB.blue,
      strokeWidth: 1.6
    }));
  }), function () {
    var ids = _toConsumableArray(sel.nodes);
    if (ids.length !== 1) return null;
    var fid = ids[0];
    var cn = M.nodes.find(function (n) {
      return n.id === fid;
    });
    if (!cn || !domOpen(cn.dom) || !visN(cn)) return null;
    var o = off(cn.dom);
    var c = {
      x: cn.x + NW / 2 + o.dx,
      y: cn.y + NHt / 2 + o.dy
    };
    var conns = [];
    M.wires.forEach(function (w) {
      if (w.a === fid) {
        var t = M.nodes.find(function (n) {
          return n.id === w.b;
        });
        if (t) {
          var A = nodeAnchor(w.b);
          if (A) conns.push({
            dir: 'out',
            why: w.why,
            t: w.t || sigOf(cn),
            to: A,
            title: t.title,
            open: domOpen(t.dom),
            oid: w.b
          });
        }
      } else if (w.b === fid) {
        var s = M.nodes.find(function (n) {
          return n.id === w.a;
        });
        if (s) {
          var _A = nodeAnchor(w.a);
          if (_A) conns.push({
            dir: 'in',
            why: w.why,
            t: w.t || sigOf(s),
            to: _A,
            title: s.title,
            open: domOpen(s.dom),
            oid: w.a
          });
        }
      }
    });
    if (!conns.length) return null;
    var hx = NW / 2 + 7,
      hy = NHt / 2 + 7;
    return /*#__PURE__*/React.createElement("g", null, conns.map(function (cc, i) {
      var ang = Math.atan2(cc.to.y - c.y, cc.to.x - c.x);
      var tmin = Math.min(Math.abs(Math.cos(ang)) < 1e-3 ? 1e6 : hx / Math.abs(Math.cos(ang)), Math.abs(Math.sin(ang)) < 1e-3 ? 1e6 : hy / Math.abs(Math.sin(ang)));
      var port = {
        x: c.x + Math.cos(ang) * tmin,
        y: c.y + Math.sin(ang) * tmin
      };
      var col = typeColOf(cc.t);
      var lab = (cc.t || 'any') + ' ' + (cc.dir === 'out' ? '▸' : '◂') + ' ' + (cc.title || '').slice(0, 20);
      var lx = port.x + (cc.to.x - port.x) * 0.42,
        ly = port.y + (cc.to.y - port.y) * 0.42;
      var ah = 7;
      var a2 = cc.dir === 'out' ? fid : cc.oid,
        b2 = cc.dir === 'out' ? cc.oid : fid;
      return /*#__PURE__*/React.createElement("g", {
        key: i
      }, /*#__PURE__*/React.createElement("path", {
        d: "M".concat(port.x, ",").concat(port.y, " L").concat(cc.to.x, ",").concat(cc.to.y),
        stroke: "transparent",
        strokeWidth: 13,
        style: {
          cursor: 'context-menu',
          pointerEvents: 'stroke'
        },
        onContextMenu: function onContextMenu(e) {
          e.preventDefault();
          e.stopPropagation();
          onWireContext && onWireContext(a2, b2, e.clientX, e.clientY);
        }
      }), /*#__PURE__*/React.createElement("g", {
        style: {
          pointerEvents: 'none'
        }
      }, /*#__PURE__*/React.createElement("path", {
        d: "M".concat(port.x, ",").concat(port.y, " L").concat(cc.to.x, ",").concat(cc.to.y),
        stroke: col,
        strokeWidth: 2,
        opacity: 0.92,
        strokeDasharray: cc.open ? '0' : '6 4'
      }), /*#__PURE__*/React.createElement("path", {
        d: "M".concat(cc.to.x - Math.cos(ang) * 14 - Math.cos(ang - 0.5) * ah, ",").concat(cc.to.y - Math.sin(ang) * 14 - Math.sin(ang - 0.5) * ah, " L").concat(cc.to.x - Math.cos(ang) * 14, ",").concat(cc.to.y - Math.sin(ang) * 14, " L").concat(cc.to.x - Math.cos(ang) * 14 - Math.cos(ang + 0.5) * ah, ",").concat(cc.to.y - Math.sin(ang) * 14 - Math.sin(ang + 0.5) * ah),
        fill: "none",
        stroke: col,
        strokeWidth: 2
      }), /*#__PURE__*/React.createElement("circle", {
        cx: port.x,
        cy: port.y,
        r: 4.5,
        fill: HB.card,
        stroke: col,
        strokeWidth: 2
      }), /*#__PURE__*/React.createElement("circle", {
        cx: port.x,
        cy: port.y,
        r: 1.6,
        fill: col
      }), /*#__PURE__*/React.createElement("g", {
        transform: "translate(".concat(lx, ",").concat(ly, ")")
      }, /*#__PURE__*/React.createElement("rect", {
        x: -lab.length * 3.05 - 6,
        y: -9,
        width: lab.length * 6.1 + 12,
        height: 18,
        rx: 9,
        fill: HB.card,
        stroke: col,
        strokeWidth: 0.8,
        opacity: 0.97
      }), /*#__PURE__*/React.createElement("text", {
        x: 0,
        y: 4,
        fontSize: cardFs(9.5),
        fontFamily: HB.mono,
        textAnchor: "middle",
        fill: col
      }, lab))));
    }), /*#__PURE__*/React.createElement("g", {
      transform: "translate(".concat(c.x, ",").concat(cn.y + o.dy - 14, ")"),
      style: {
        pointerEvents: 'none'
      }
    }, /*#__PURE__*/React.createElement("rect", {
      x: -64,
      y: -11,
      width: 128,
      height: 20,
      rx: 10,
      fill: HB.paper2,
      stroke: HB.line,
      strokeWidth: 1
    }), /*#__PURE__*/React.createElement("text", {
      x: 0,
      y: 3,
      fontSize: cardFs(9),
      fontFamily: HB.mono,
      textAnchor: "middle",
      fill: HB.ink
    }, conns.filter(function (c) {
      return c.dir === 'out';
    }).length, " out \xB7 ", conns.filter(function (c) {
      return c.dir === 'in';
    }).length, " in \xB7 right-click wire to cut")));
  }(), wire && function () {
    var f = M.nodes.find(function (n) {
      return n.id === wire.from;
    });
    if (!f) return null;
    var o = off(f.dom);
    var fx = f.x + NW + o.dx,
      fy = f.y + NHt / 2 + o.dy;
    return /*#__PURE__*/React.createElement("g", {
      style: {
        pointerEvents: 'none'
      }
    }, /*#__PURE__*/React.createElement("path", {
      d: "M".concat(fx, ",").concat(fy, " C").concat(fx + 70, ",").concat(fy, " ").concat(wire.x - 70, ",").concat(wire.y, " ").concat(wire.x, ",").concat(wire.y),
      stroke: HB.accent,
      strokeWidth: 2.4,
      strokeDasharray: "6 4",
      fill: "none"
    }), /*#__PURE__*/React.createElement("circle", {
      cx: wire.x,
      cy: wire.y,
      r: 5,
      fill: HB.accent
    }));
  }(), marquee && /*#__PURE__*/React.createElement("rect", {
    x: marquee.x,
    y: marquee.y,
    width: marquee.w,
    height: marquee.h,
    fill: HB.accent,
    fillOpacity: 0.08,
    stroke: HB.accent,
    strokeWidth: 1.4,
    strokeDasharray: "6 4"
  })));
});
Object.assign(window, {
  MapCanvas: MapCanvas,
  STC: STC,
  catCol: catCol,
  NW_ATLAS: NW,
  DETAIL_W: DETAIL_W,
  nodePipeline: nodePipeline,
  nodePorts: nodePorts,
  sigOf: sigOf,
  typeOf: typeOf,
  SIGNAL: SIGNAL,
  TYPECOL: TYPECOL,
  typeColOf: typeColOf,
  archCanConnect: archCanConnect
});
