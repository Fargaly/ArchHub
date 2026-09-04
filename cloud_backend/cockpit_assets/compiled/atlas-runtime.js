function _toConsumableArray(r) { return _arrayWithoutHoles(r) || _iterableToArray(r) || _unsupportedIterableToArray(r) || _nonIterableSpread(); }
function _nonIterableSpread() { throw new TypeError("Invalid attempt to spread non-iterable instance.\nIn order to be iterable, non-array objects must have a [Symbol.iterator]() method."); }
function _unsupportedIterableToArray(r, a) { if (r) { if ("string" == typeof r) return _arrayLikeToArray(r, a); var t = {}.toString.call(r).slice(8, -1); return "Object" === t && r.constructor && (t = r.constructor.name), "Map" === t || "Set" === t ? Array.from(r) : "Arguments" === t || /^(?:Ui|I)nt(?:8|16|32)(?:Clamped)?Array$/.test(t) ? _arrayLikeToArray(r, a) : void 0; } }
function _iterableToArray(r) { if ("undefined" != typeof Symbol && null != r[Symbol.iterator] || null != r["@@iterator"]) return Array.from(r); }
function _arrayWithoutHoles(r) { if (Array.isArray(r)) return _arrayLikeToArray(r); }
function _arrayLikeToArray(r, a) { (null == a || a > r.length) && (a = r.length); for (var e = 0, n = Array(a); e < a; e++) n[e] = r[e]; return n; }
// atlas-runtime.jsx — the WORKING-GRAPH runtime, shared logic with the app's node canvas.
// Nodes run; wires carry the run downstream; editing marks dependents stale; watcher
// nodes show live results; every run is recorded (history / variants tree).
// Pure helpers + small UI + CSS. Exposed on window.RT.

var _window = window,
  HB = _window.HB;
var RT_COL = {
  fresh: HB.green,
  stale: HB.amber,
  running: HB.accent,
  error: HB.red,
  idle: HB.inkMute
};
var rtState = function rtState(n) {
  return n && n.rt && n.rt.state || 'idle';
};
var rtRuns = function rtRuns(n) {
  return n && n.rt && n.rt.runs || [];
};

// plausible result a node emits, by category — what a watcher would display
function rtResult(node) {
  var c = node.cat || 'logic';
  var map = {
    vision: '3 masses · 1,240 px → mesh',
    compose: 'sheet set A.101–A.108 · 8 sheets',
    output: '47 dimensions placed · 4.2s',
    transform: '212 elements remapped',
    extract: '18 rooms · 96 walls',
    logic: 'ok · 12 rules passed',
    skill: 'pipeline ✓ 6 stages',
    connector: 'session live · 41ms p50',
    host: 'handshake ✓ :48884',
    ai: '1,820 tok · $0.04',
    input: 'sketch.png · 1.2 MB',
    trigger: 'fired · 1 event',
    watch: '—',
    preview: '—',
    note: '—'
  };
  return map[c] || 'ok';
}
var RUN_SEQ = 1;
function mkRun(node, variantOf) {
  var ms = 200 + Math.floor(Math.random() * 1400);
  return {
    id: 'r' + RUN_SEQ++,
    n: rtRuns(node).length + 1,
    t: Date.now(),
    ms: ms,
    ok: Math.random() > 0.08,
    result: rtResult(node),
    variantOf: variantOf || null
  };
}

// downstream node ids reachable from id along out-wires (1 hop — direct dependents)
function downstream(M, id) {
  var out = [];
  M.wires.forEach(function (w) {
    if (w.a === id) out.push(w.b);
  });
  return _toConsumableArray(new Set(out));
}
function upstreamIds(M, id) {
  var ins = [];
  M.wires.forEach(function (w) {
    if (w.b === id) ins.push(w.a);
  });
  return _toConsumableArray(new Set(ins));
}

// inject runtime CSS once
if (typeof document !== 'undefined' && !document.getElementById('rt-anim')) {
  var s = document.createElement('style');
  s.id = 'rt-anim';
  s.textContent = "\n    @keyframes rtRing{0%{opacity:.9;r:4}70%{opacity:0;r:14}100%{opacity:0;r:14}}\n    @keyframes rtDash{to{stroke-dashoffset:-22}}\n    .rt-run-ring{animation:rtRing 1.3s ease-out infinite}\n    .rt-flow{stroke-dasharray:6 6;animation:rtDash .6s linear infinite}\n  ";
  document.head.appendChild(s);
}

// a small runtime chip for inspectors
function RTChip(_ref) {
  var state = _ref.state;
  var c = RT_COL[state] || HB.inkMute;
  return /*#__PURE__*/React.createElement("span", {
    style: {
      display: 'inline-flex',
      alignItems: 'center',
      gap: 5,
      padding: '3px 9px',
      borderRadius: 999,
      background: c + '1e',
      border: "1px solid ".concat(c),
      color: c,
      fontFamily: HB.mono,
      fontSize: 9.5,
      letterSpacing: '0.08em',
      textTransform: 'uppercase'
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: 6,
      height: 6,
      borderRadius: '50%',
      background: c,
      animation: state === 'running' ? 'rtRing 1.2s infinite' : 'none'
    }
  }), state);
}

// the Runs / history (tree) tab body
function RunsBody(_ref2) {
  var node = _ref2.node,
    onRun = _ref2.onRun,
    onVariant = _ref2.onVariant;
  var runs = rtRuns(node).slice().reverse();
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 12
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 8
    }
  }, /*#__PURE__*/React.createElement(RTChip, {
    state: rtState(node)
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: HB.mono,
      fontSize: 10,
      color: HB.inkMute
    }
  }, runs.length, " runs"), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1
    }
  }), /*#__PURE__*/React.createElement("button", {
    onClick: onRun,
    style: {
      display: 'inline-flex',
      alignItems: 'center',
      gap: 6,
      padding: '6px 12px',
      borderRadius: 7,
      border: 'none',
      background: HB.accent,
      color: '#fff',
      cursor: 'pointer',
      fontFamily: HB.mono,
      fontSize: 11,
      fontWeight: 600
    }
  }, "\u25B8 Run")), runs.length === 0 && /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: HB.serif,
      fontStyle: 'italic',
      fontSize: 13,
      color: HB.inkMute
    }
  }, "No runs yet. Run it to produce a result and start the history tree."), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 0
    }
  }, runs.map(function (r, i) {
    return /*#__PURE__*/React.createElement("div", {
      key: r.id,
      style: {
        display: 'flex',
        gap: 10,
        paddingLeft: r.variantOf ? 18 : 0
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center'
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        width: 10,
        height: 10,
        borderRadius: '50%',
        background: r.ok ? HB.green : HB.red,
        marginTop: 6
      }
    }), i < runs.length - 1 && /*#__PURE__*/React.createElement("span", {
      style: {
        flex: 1,
        width: 1.5,
        background: HB.line
      }
    })), /*#__PURE__*/React.createElement("div", {
      style: {
        flex: 1,
        paddingBottom: 12
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        alignItems: 'baseline',
        gap: 7
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        fontFamily: HB.mono,
        fontSize: 11.5,
        color: HB.ink
      }
    }, r.variantOf ? '⌥ variant' : 'run', " #", r.n), /*#__PURE__*/React.createElement("span", {
      style: {
        fontFamily: HB.mono,
        fontSize: 9.5,
        color: r.ok ? HB.green : HB.red
      }
    }, r.ok ? '✓' : '✗ failed'), /*#__PURE__*/React.createElement("span", {
      style: {
        fontFamily: HB.mono,
        fontSize: 9.5,
        color: HB.inkMute
      }
    }, r.ms, "ms"), /*#__PURE__*/React.createElement("button", {
      onClick: function onClick() {
        return onVariant(r);
      },
      title: "Branch a variant from this run",
      style: {
        marginLeft: 'auto',
        border: "1px solid ".concat(HB.line),
        background: HB.paper2,
        color: HB.inkSoft,
        borderRadius: 6,
        padding: '2px 7px',
        cursor: 'pointer',
        fontFamily: HB.mono,
        fontSize: 9
      }
    }, "\u2325 variant")), /*#__PURE__*/React.createElement("div", {
      style: {
        fontFamily: HB.mono,
        fontSize: 11,
        color: HB.inkSoft,
        marginTop: 3
      }
    }, r.result)));
  })));
}
Object.assign(window, {
  RT: {
    RT_COL: RT_COL,
    rtState: rtState,
    rtRuns: rtRuns,
    rtResult: rtResult,
    mkRun: mkRun,
    downstream: downstream,
    upstreamIds: upstreamIds,
    RTChip: RTChip,
    RunsBody: RunsBody
  }
});
