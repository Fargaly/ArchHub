function _typeof(o) { "@babel/helpers - typeof"; return _typeof = "function" == typeof Symbol && "symbol" == typeof Symbol.iterator ? function (o) { return typeof o; } : function (o) { return o && "function" == typeof Symbol && o.constructor === Symbol && o !== Symbol.prototype ? "symbol" : typeof o; }, _typeof(o); }
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
// atlas-side.jsx — the RIGHT sidebar: the cockpit's agentic surface.
// Three lenses, all node-driven: ACTIVITY (agent notifications + the Attention
// node's ranked feed), SESSIONS (live conversations with the founder's agents),
// HISTORY (the run-tree of the whole grand map). Everything here is produced by
// nodes on the map — nothing is hardcoded importance.

var _window = window,
  HB = _window.HB;

// Matches the left rail's chrome spec (see ltab / secStyle / PanelLabel) so the two
// panels framing the map align row-for-row.
var tabBtn = function tabBtn(on) {
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
var sideSec = {
  padding: '15px 16px',
  borderBottom: "1px solid ".concat(HB.lineSoft)
};
var sideLabel = {
  fontFamily: HB.mono,
  fontSize: 8.5,
  color: HB.inkMute,
  letterSpacing: '0.16em',
  marginBottom: 9
};
function ago(t) {
  var s = Math.floor((Date.now() - t) / 1000);
  if (s < 60) return s + 's';
  var m = Math.floor(s / 60);
  if (m < 60) return m + 'm';
  var h = Math.floor(m / 60);
  if (h < 24) return h + 'h';
  return Math.floor(h / 24) + 'd';
}

// deterministic seed sessions from the founder's agents
function seedSessions(DB, M) {
  var dn = function dn(k) {
    return (M.domains.find(function (d) {
      return d.key === k;
    }) || {}).title || k;
  };
  var tmpl = [{
    topic: 'Monetization gaps → first 3 to build',
    dom: 'monetization',
    msgs: [['founder', 'What unlocks revenue fastest?'], ['agent', 'Three vision nodes gate billing: Stripe Connect, Usage Meter, Plan Gating. I can scaffold Usage Meter first — it feeds the other two.'], ['founder', 'Do it. Wire it to the billing daemon.']]
  }, {
    topic: 'Brain recall latency regression',
    dom: 'brain',
    msgs: [['agent', 'Recall p50 rose 41ms→63ms after the embedding swap.'], ['founder', 'Roll back or fix?'], ['agent', 'Fixing — re-indexing the fact store now, ETA 4m. Will report.']]
  }, {
    topic: 'Connector fleet health sweep',
    dom: 'connectors',
    msgs: [['agent', 'Ran a sweep: Revit host dropped 2 handshakes overnight.'], ['founder', 'Quarantine it and notify me if it repeats.']]
  }, {
    topic: 'Self-extension proposal review',
    dom: 'selfext',
    msgs: [['agent', 'I drafted a new skill node: auto-dimension cleanup. Awaiting your approval to merge into the graph.'], ['founder', 'Show me its pipeline first.']]
  }];
  return tmpl.map(function (t, i) {
    var ag = DB.agents[i % DB.agents.length];
    return {
      id: 's' + i,
      topic: t.topic,
      dom: t.dom,
      domName: dn(t.dom),
      agent: ag,
      t: Date.now() - (i * 1000 * 60 * 37 + 1000 * 60 * 6),
      open: i === 0,
      msgs: t.msgs.map(function (m, j) {
        return {
          who: m[0],
          name: m[0] === 'agent' ? ag.name : 'You',
          text: m[1],
          t: Date.now() - (t.msgs.length - j) * 1000 * 60 * 4
        };
      })
    };
  });
}
function SessionComposer(_ref) {
  var agentName = _ref.agentName,
    onSend = _ref.onSend;
  var _React$useState = React.useState(''),
    _React$useState2 = _slicedToArray(_React$useState, 2),
    draft = _React$useState2[0],
    setDraft = _React$useState2[1];
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 6,
      marginTop: 2
    }
  }, /*#__PURE__*/React.createElement("input", {
    value: draft,
    onChange: function onChange(e) {
      return setDraft(e.target.value);
    },
    onKeyDown: function onKeyDown(e) {
      if (e.key === 'Enter' && draft.trim()) {
        onSend(draft.trim());
        setDraft('');
      }
    },
    placeholder: 'Message ' + agentName + '…',
    style: {
      flex: 1,
      padding: '7px 10px',
      borderRadius: 8,
      border: "1px solid ".concat(HB.line),
      background: HB.card,
      color: HB.ink,
      fontSize: 12,
      outline: 'none',
      fontFamily: HB.sans
    }
  }));
}
function AgenticPanel(_ref2) {
  var M = _ref2.M,
    DB = _ref2.DB,
    assign = _ref2.assign,
    attention = _ref2.attention,
    onGoto = _ref2.onGoto,
    onTuneAttention = _ref2.onTuneAttention,
    attNode = _ref2.attNode,
    setColl = _ref2.setColl,
    flash = _ref2.flash;
  var _React$useState3 = React.useState('activity'),
    _React$useState4 = _slicedToArray(_React$useState3, 2),
    tab = _React$useState4[0],
    setTab = _React$useState4[1];
  var _React$useState5 = React.useState(function () {
      return seedSessions(DB, M);
    }),
    _React$useState6 = _slicedToArray(_React$useState5, 2),
    sessions = _React$useState6[0],
    setSessions = _React$useState6[1];

  // recent runs across the whole map → the notification stream
  var recent = [];
  M.nodes.forEach(function (n) {
    return (n.rt && n.rt.runs || []).forEach(function (r) {
      return recent.push(_objectSpread(_objectSpread({}, r), {}, {
        node: n
      }));
    });
  });
  recent.sort(function (a, b) {
    return b.t - a.t;
  });
  var stream = recent.slice(0, 12);
  var agentsByNode = function agentsByNode(id) {
    return (assign[id] || []).map(function (aid) {
      return DB.agents.find(function (a) {
        return a.id === aid;
      });
    }).filter(Boolean);
  };
  var totalRuns = recent.length;
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      height: '100%'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      borderBottom: "1px solid ".concat(HB.line),
      flexShrink: 0,
      background: HB.card
    }
  }, [['activity', 'Activity', 'bolt'], ['routing', 'Routing', 'sliders'], ['sessions', 'Sessions', 'agent'], ['history', 'History', 'pulse']].map(function (_ref3) {
    var _ref4 = _slicedToArray(_ref3, 3),
      k = _ref4[0],
      l = _ref4[1],
      ic = _ref4[2];
    return /*#__PURE__*/React.createElement("button", {
      key: k,
      onClick: function onClick() {
        return setTab(k);
      },
      style: tabBtn(tab === k)
    }, /*#__PURE__*/React.createElement(CKIcon, {
      name: ic,
      size: 12
    }), l);
  })), /*#__PURE__*/React.createElement("div", {
    className: "hb-scroll",
    style: {
      flex: 1,
      overflow: 'auto'
    }
  }, tab === 'activity' && /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: _objectSpread(_objectSpread({}, sideSec), {}, {
      background: HB.paper2
    })
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 7,
      marginBottom: 4
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: 7,
      height: 7,
      borderRadius: '50%',
      background: HB.accent,
      boxShadow: "0 0 0 3px ".concat(HB.accent, "22")
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: HB.mono,
      fontSize: 9,
      color: HB.accent,
      letterSpacing: '0.16em',
      flex: 1
    }
  }, "WHAT MATTERS NOW"), /*#__PURE__*/React.createElement("button", {
    onClick: onTuneAttention,
    title: "Open the Attention node to tune its weights",
    style: {
      display: 'inline-flex',
      alignItems: 'center',
      gap: 4,
      border: "1px solid ".concat(HB.line),
      background: HB.card,
      color: HB.inkSoft,
      borderRadius: 6,
      padding: '3px 8px',
      cursor: 'pointer',
      fontFamily: HB.mono,
      fontSize: 9
    }
  }, /*#__PURE__*/React.createElement(CKIcon, {
    name: "gear",
    size: 10
  }), "tune")), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: HB.mono,
      fontSize: 9,
      color: HB.inkMute,
      marginBottom: 10,
      lineHeight: 1.4
    }
  }, "ranked by the ", /*#__PURE__*/React.createElement("b", {
    style: {
      color: HB.inkSoft
    }
  }, "Attention"), " node \u2014 a parametric node you control, not a fixed rule."), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 6
    }
  }, attention.length === 0 && /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: HB.serif,
      fontStyle: 'italic',
      fontSize: 13,
      color: HB.inkMute
    }
  }, "Nothing flagged. The graph is calm."), attention.map(function (it, i) {
    var c = {
      red: HB.red,
      accent: HB.accent,
      blue: HB.blue,
      green: HB.green
    }[it.tone];
    var ic = {
      blocked: 'x',
      gap: 'eye',
      agent: 'agent'
    }[it.kind];
    return /*#__PURE__*/React.createElement("button", {
      key: i,
      onClick: function onClick() {
        return onGoto(it);
      },
      className: "hb-rowh",
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 9,
        padding: '8px 10px',
        borderRadius: 8,
        cursor: 'pointer',
        textAlign: 'left',
        border: "1px solid ".concat(HB.line),
        borderLeft: "3px solid ".concat(c),
        background: HB.card
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        width: 22,
        height: 22,
        borderRadius: 6,
        display: 'grid',
        placeItems: 'center',
        background: c + '1c',
        color: c,
        flexShrink: 0
      }
    }, /*#__PURE__*/React.createElement(CKIcon, {
      name: ic,
      size: 12
    })), /*#__PURE__*/React.createElement("span", {
      style: {
        flex: 1,
        minWidth: 0
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 12.5,
        fontWeight: 600,
        color: HB.ink,
        display: 'block',
        overflow: 'hidden',
        textOverflow: 'ellipsis',
        whiteSpace: 'nowrap'
      }
    }, it.label), /*#__PURE__*/React.createElement("span", {
      style: {
        fontFamily: HB.mono,
        fontSize: 9.5,
        color: HB.inkMute
      }
    }, it.sub, it.score != null ? " \xB7 ".concat(it.score) : '')), /*#__PURE__*/React.createElement(CKIcon, {
      name: "eye",
      size: 13,
      color: HB.inkMute
    }));
  }))), /*#__PURE__*/React.createElement("div", {
    style: sideSec
  }, /*#__PURE__*/React.createElement("div", {
    style: _objectSpread(_objectSpread({}, sideLabel), {}, {
      display: 'flex',
      justifyContent: 'space-between'
    })
  }, /*#__PURE__*/React.createElement("span", null, "AGENT ACTIVITY"), /*#__PURE__*/React.createElement("span", {
    style: {
      color: HB.inkDim
    }
  }, totalRuns, " total")), stream.length === 0 && /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: HB.serif,
      fontStyle: 'italic',
      fontSize: 13,
      color: HB.inkMute
    }
  }, "No runs yet. Run a node \u2014 its agents report here."), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 2
    }
  }, stream.map(function (r, i) {
    var ags = agentsByNode(r.node.id);
    return /*#__PURE__*/React.createElement("button", {
      key: r.id,
      onClick: function onClick() {
        return onGoto({
          nodeId: r.node.id,
          dom: r.node.dom
        });
      },
      className: "hb-rowh",
      style: {
        display: 'flex',
        alignItems: 'flex-start',
        gap: 9,
        padding: '8px',
        borderRadius: 8,
        cursor: 'pointer',
        textAlign: 'left',
        border: 'none',
        background: 'transparent'
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        width: 18,
        height: 18,
        borderRadius: 5,
        marginTop: 1,
        display: 'grid',
        placeItems: 'center',
        background: (r.ok ? HB.green : HB.red) + '1e',
        color: r.ok ? HB.green : HB.red,
        flexShrink: 0,
        fontSize: 10
      }
    }, r.ok ? '✓' : '✗'), /*#__PURE__*/React.createElement("span", {
      style: {
        flex: 1,
        minWidth: 0
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 12,
        color: HB.ink,
        display: 'block'
      }
    }, /*#__PURE__*/React.createElement("b", {
      style: {
        fontWeight: 600
      }
    }, ags[0] ? ags[0].name : 'System'), " ran ", /*#__PURE__*/React.createElement("span", {
      style: {
        color: HB.inkSoft
      }
    }, r.node.title)), /*#__PURE__*/React.createElement("span", {
      style: {
        fontFamily: HB.mono,
        fontSize: 9.5,
        color: HB.inkMute
      }
    }, r.result, " \xB7 ", r.ms, "ms \xB7 ", ago(r.t), " ago")));
  })))), tab === 'routing' && function () {
    var models = DB.models || [];
    var live = models.filter(function (m) {
      return m.status !== 'disabled';
    });
    // task classes present anywhere in the fleet, plus the ones the app always needs
    var classes = _toConsumableArray(new Set(['intent', 'vision', 'compose', 'critique', 'extract', 'fallback', 'offline'].concat(_toConsumableArray(models.flatMap(function (m) {
      return m.tasks || [];
    })))));
    // rough monthly volume per class (calls, and tokens per call) — the basis of the estimate
    var VOL = {
      intent: [42000, 1.6],
      vision: [8600, 4.2],
      compose: [15400, 3.1],
      critique: [3100, 5.4],
      extract: [26000, 2.2],
      fallback: [4200, 1.8],
      offline: [1900, 1.4]
    };
    var ownerOf = function ownerOf(cls) {
      return (live.find(function (m) {
        return (m.tasks || []).includes(cls);
      }) || {}).id || '';
    };
    var route = function route(cls, id) {
      setColl && setColl('models', function (ms) {
        return ms.map(function (m) {
          var has = (m.tasks || []).includes(cls);
          if (m.id === id && !has) return _objectSpread(_objectSpread({}, m), {}, {
            tasks: [].concat(_toConsumableArray(m.tasks || []), [cls])
          });
          if (m.id !== id && has) return _objectSpread(_objectSpread({}, m), {}, {
            tasks: (m.tasks || []).filter(function (t) {
              return t !== cls;
            })
          });
          return m;
        });
      });
      var nm = (models.find(function (m) {
        return m.id === id;
      }) || {}).name || 'none';
      flash && flash(cls + ' → ' + nm);
    };
    // spend follows the routing: each class's volume is billed at its owner's rate
    var spendByVendor = {};
    var total = 0;
    classes.forEach(function (cls) {
      var m = live.find(function (x) {
        return (x.tasks || []).includes(cls);
      });
      if (!m) return;
      var _ref5 = VOL[cls] || [4000, 2],
        _ref6 = _slicedToArray(_ref5, 2),
        calls = _ref6[0],
        ktok = _ref6[1];
      var usd = calls * ktok / 1000 * (m.inCost * 0.75 + m.outCost * 0.25);
      spendByVendor[m.vendor] = (spendByVendor[m.vendor] || 0) + usd;
      total += usd;
    });
    var vendors = Object.entries(spendByVendor).sort(function (a, b) {
      return b[1] - a[1];
    });
    var issues = DB.issues || [];
    var openIss = issues.filter(function (i) {
      return i.status !== 'resolved';
    });
    var agents = DB.agents || [];
    var D = String.fromCharCode(36);
    var money = function money(v) {
      return v >= 1000 ? D + (v / 1000).toFixed(1) + 'k' : D + Math.round(v);
    };
    var PAL = [HB.accent, HB.blue, HB.purple, HB.green, HB.amber];
    return /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
      style: sideSec
    }, /*#__PURE__*/React.createElement("div", {
      style: _objectSpread(_objectSpread({}, sideLabel), {}, {
        display: 'flex',
        justifyContent: 'space-between'
      })
    }, /*#__PURE__*/React.createElement("span", null, "MODEL ROUTING"), /*#__PURE__*/React.createElement("span", {
      style: {
        color: HB.inkSoft
      }
    }, classes.length, " task classes")), /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        flexDirection: 'column',
        gap: 5
      }
    }, classes.map(function (cls) {
      return /*#__PURE__*/React.createElement("div", {
        key: cls,
        style: {
          display: 'flex',
          alignItems: 'center',
          gap: 8
        }
      }, /*#__PURE__*/React.createElement("span", {
        style: {
          fontFamily: HB.mono,
          fontSize: 10,
          color: HB.ink,
          width: 62,
          flexShrink: 0
        }
      }, cls), /*#__PURE__*/React.createElement("select", {
        value: ownerOf(cls),
        onChange: function onChange(e) {
          return route(cls, e.target.value);
        },
        style: {
          flex: 1,
          minWidth: 0,
          padding: '5px 6px',
          borderRadius: 6,
          border: '1px solid ' + HB.line,
          background: HB.paper,
          color: HB.ink,
          fontFamily: HB.mono,
          fontSize: 10
        }
      }, /*#__PURE__*/React.createElement("option", {
        value: ""
      }, "\u2014 unrouted \u2014"), live.map(function (m) {
        return /*#__PURE__*/React.createElement("option", {
          key: m.id,
          value: m.id
        }, m.name);
      })));
    })), /*#__PURE__*/React.createElement("div", {
      style: {
        fontFamily: HB.mono,
        fontSize: 9,
        color: HB.inkSoft,
        marginTop: 9,
        lineHeight: 1.5
      }
    }, "Reassigning a class rewrites the fleet and re-prices the estimate below.")), /*#__PURE__*/React.createElement("div", {
      style: sideSec
    }, /*#__PURE__*/React.createElement("div", {
      style: _objectSpread(_objectSpread({}, sideLabel), {}, {
        display: 'flex',
        justifyContent: 'space-between'
      })
    }, /*#__PURE__*/React.createElement("span", null, "SPEND \xB7 EST / MONTH"), /*#__PURE__*/React.createElement("span", {
      style: {
        color: HB.accent,
        fontSize: 11
      }
    }, money(total))), /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        height: 8,
        borderRadius: 4,
        overflow: 'hidden',
        background: HB.paper,
        marginBottom: 9
      }
    }, vendors.map(function (_ref7, k) {
      var _ref8 = _slicedToArray(_ref7, 2),
        v = _ref8[0],
        usd = _ref8[1];
      return /*#__PURE__*/React.createElement("div", {
        key: v,
        style: {
          width: usd / (total || 1) * 100 + '%',
          background: PAL[k % 5]
        }
      });
    })), /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        flexDirection: 'column',
        gap: 4
      }
    }, vendors.map(function (_ref9, k) {
      var _ref0 = _slicedToArray(_ref9, 2),
        v = _ref0[0],
        usd = _ref0[1];
      return /*#__PURE__*/React.createElement("div", {
        key: v,
        style: {
          display: 'flex',
          alignItems: 'center',
          gap: 7,
          fontFamily: HB.mono,
          fontSize: 10.5
        }
      }, /*#__PURE__*/React.createElement("span", {
        style: {
          width: 8,
          height: 8,
          borderRadius: 2,
          background: PAL[k % 5],
          flexShrink: 0
        }
      }), /*#__PURE__*/React.createElement("span", {
        style: {
          flex: 1,
          color: HB.ink
        }
      }, v), /*#__PURE__*/React.createElement("span", {
        style: {
          color: HB.inkSoft
        }
      }, (usd / (total || 1) * 100).toFixed(0), "%"), /*#__PURE__*/React.createElement("span", {
        style: {
          color: HB.ink,
          width: 48,
          textAlign: 'right'
        }
      }, money(usd)));
    }), !vendors.length && /*#__PURE__*/React.createElement("div", {
      style: {
        fontFamily: HB.serif,
        fontStyle: 'italic',
        fontSize: 13,
        color: HB.inkSoft
      }
    }, "Nothing routed \u2014 no spend."))), /*#__PURE__*/React.createElement("div", {
      style: _objectSpread(_objectSpread({}, sideSec), {}, {
        borderBottom: 'none'
      })
    }, /*#__PURE__*/React.createElement("div", {
      style: _objectSpread(_objectSpread({}, sideLabel), {}, {
        display: 'flex',
        justifyContent: 'space-between'
      })
    }, /*#__PURE__*/React.createElement("span", null, "INCIDENTS"), /*#__PURE__*/React.createElement("span", {
      style: {
        color: openIss.length ? HB.red : HB.green
      }
    }, openIss.length, " open")), /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        flexDirection: 'column',
        gap: 6
      }
    }, openIss.slice(0, 6).map(function (it) {
      return /*#__PURE__*/React.createElement("div", {
        key: it.id,
        style: {
          padding: '8px 9px',
          borderRadius: 7,
          background: HB.paper2,
          border: '1px solid ' + HB.line
        }
      }, /*#__PURE__*/React.createElement("div", {
        style: {
          display: 'flex',
          alignItems: 'center',
          gap: 6
        }
      }, /*#__PURE__*/React.createElement("span", {
        style: {
          width: 6,
          height: 6,
          borderRadius: '50%',
          background: it.level === 'error' ? HB.red : HB.amber,
          flexShrink: 0
        }
      }), /*#__PURE__*/React.createElement("span", {
        style: {
          fontFamily: HB.sans,
          fontSize: 12,
          color: HB.ink,
          flex: 1,
          minWidth: 0,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap'
        }
      }, it.title), /*#__PURE__*/React.createElement("span", {
        style: {
          fontFamily: HB.mono,
          fontSize: 9,
          color: HB.inkSoft
        }
      }, "\xD7", it.count || 1)), /*#__PURE__*/React.createElement("div", {
        style: {
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          marginTop: 7
        }
      }, /*#__PURE__*/React.createElement("select", {
        value: it.owner || '',
        onChange: function onChange(e) {
          var nm = e.target.value;
          setColl && setColl('issues', function (xs) {
            return xs.map(function (x) {
              return x.id === it.id ? _objectSpread(_objectSpread({}, x), {}, {
                owner: nm
              }) : x;
            });
          });
          flash && flash(nm ? 'Assigned to ' + nm : 'Unassigned');
        },
        style: {
          flex: 1,
          minWidth: 0,
          padding: '4px 5px',
          borderRadius: 5,
          border: '1px solid ' + HB.line,
          background: HB.paper,
          color: HB.ink,
          fontFamily: HB.mono,
          fontSize: 9.5
        }
      }, /*#__PURE__*/React.createElement("option", {
        value: ""
      }, "\u2014 unassigned \u2014"), agents.map(function (a) {
        return /*#__PURE__*/React.createElement("option", {
          key: a.id || a.name,
          value: a.name
        }, a.name);
      })), /*#__PURE__*/React.createElement("button", {
        onClick: function onClick() {
          setColl && setColl('issues', function (xs) {
            return xs.map(function (x) {
              return x.id === it.id ? _objectSpread(_objectSpread({}, x), {}, {
                status: 'resolved'
              }) : x;
            });
          });
          flash && flash('Resolved');
        },
        style: {
          fontFamily: HB.mono,
          fontSize: 9.5,
          padding: '4px 8px',
          borderRadius: 5,
          border: '1px solid ' + HB.green,
          background: 'transparent',
          color: HB.green,
          cursor: 'pointer',
          flexShrink: 0
        }
      }, "resolve")));
    }), !openIss.length && /*#__PURE__*/React.createElement("div", {
      style: {
        fontFamily: HB.serif,
        fontStyle: 'italic',
        fontSize: 13,
        color: HB.inkSoft
      }
    }, "Queue clear."))));
  }(), tab === 'sessions' && /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: _objectSpread(_objectSpread({}, sideSec), {}, {
      borderBottom: "1px solid ".concat(HB.line)
    })
  }, /*#__PURE__*/React.createElement("div", {
    style: sideLabel
  }, "CONVERSATIONS WITH YOUR AGENTS"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 8
    }
  }, sessions.map(function (s) {
    var dcol = (M.domains.find(function (d) {
      return d.key === s.dom;
    }) || {}).col || HB.accent;
    return /*#__PURE__*/React.createElement("div", {
      key: s.id,
      style: {
        border: "1px solid ".concat(HB.line),
        borderRadius: 10,
        overflow: 'hidden',
        background: HB.card
      }
    }, /*#__PURE__*/React.createElement("button", {
      onClick: function onClick() {
        return setSessions(function (ss) {
          return ss.map(function (x) {
            return x.id === s.id ? _objectSpread(_objectSpread({}, x), {}, {
              open: !x.open
            }) : x;
          });
        });
      },
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 9,
        width: '100%',
        textAlign: 'left',
        padding: '10px 11px',
        border: 'none',
        background: 'transparent',
        cursor: 'pointer'
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        width: 26,
        height: 26,
        borderRadius: 7,
        display: 'grid',
        placeItems: 'center',
        background: HB.accentSoft,
        color: HB.accentHi,
        flexShrink: 0
      }
    }, /*#__PURE__*/React.createElement(CKIcon, {
      name: "agent",
      size: 13
    })), /*#__PURE__*/React.createElement("span", {
      style: {
        flex: 1,
        minWidth: 0
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 12.5,
        fontWeight: 600,
        color: HB.ink,
        display: 'block',
        overflow: 'hidden',
        textOverflow: 'ellipsis',
        whiteSpace: 'nowrap'
      }
    }, s.topic), /*#__PURE__*/React.createElement("span", {
      style: {
        fontFamily: HB.mono,
        fontSize: 9.5,
        color: HB.inkMute
      }
    }, s.agent.name, " \xB7 ", /*#__PURE__*/React.createElement("span", {
      style: {
        color: dcol
      }
    }, s.domName), " \xB7 ", ago(s.t), " ago")), /*#__PURE__*/React.createElement("span", {
      style: {
        fontFamily: HB.mono,
        fontSize: 15,
        color: HB.inkMute,
        width: 14,
        textAlign: 'center'
      }
    }, s.open ? '▾' : '▸')), s.open && /*#__PURE__*/React.createElement("div", {
      style: {
        borderTop: "1px solid ".concat(HB.lineSoft),
        padding: '10px 11px',
        display: 'flex',
        flexDirection: 'column',
        gap: 9,
        background: HB.paper2
      }
    }, s.msgs.map(function (m, j) {
      return /*#__PURE__*/React.createElement("div", {
        key: j,
        style: {
          display: 'flex',
          flexDirection: m.who === 'founder' ? 'row-reverse' : 'row',
          gap: 8
        }
      }, /*#__PURE__*/React.createElement("span", {
        style: {
          maxWidth: '82%',
          padding: '7px 10px',
          borderRadius: 10,
          fontSize: 12,
          lineHeight: 1.45,
          background: m.who === 'founder' ? HB.accent : HB.card,
          color: m.who === 'founder' ? '#fff' : HB.ink,
          border: m.who === 'founder' ? 'none' : "1px solid ".concat(HB.line)
        }
      }, m.text));
    }), /*#__PURE__*/React.createElement(SessionComposer, {
      agentName: s.agent.name,
      onSend: function onSend(txt) {
        return setSessions(function (ss) {
          return ss.map(function (x) {
            if (x.id !== s.id) return x;
            var mine = {
              who: 'founder',
              name: 'You',
              text: txt,
              t: Date.now()
            };
            var reply = {
              who: 'agent',
              name: s.agent.name,
              text: "On it \u2014 updating the relevant nodes; I will report back in Activity.",
              t: Date.now() + 1
            };
            return _objectSpread(_objectSpread({}, x), {}, {
              msgs: x.msgs.concat([mine, reply]),
              t: Date.now()
            });
          });
        });
      }
    })));
  })))), tab === 'history' && /*#__PURE__*/React.createElement("div", {
    style: sideSec
  }, /*#__PURE__*/React.createElement("div", {
    style: sideLabel
  }, "GRAND-MAP HISTORY \xB7 RUN TREE"), recent.length === 0 && /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: HB.serif,
      fontStyle: 'italic',
      fontSize: 13,
      color: HB.inkMute
    }
  }, "No history yet. Every node run, edit, and variant is recorded here as a tree."), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column'
    }
  }, function () {
    // group by node, newest first; show each node's runs as a small branch
    var byNode = {};
    recent.forEach(function (r) {
      (byNode[r.node.id] = byNode[r.node.id] || {
        node: r.node,
        runs: []
      }).runs.push(r);
    });
    var groups = Object.values(byNode).sort(function (a, b) {
      return b.runs[0].t - a.runs[0].t;
    });
    return groups.map(function (g, gi) {
      return /*#__PURE__*/React.createElement("div", {
        key: g.node.id,
        style: {
          display: 'flex',
          gap: 10
        }
      }, /*#__PURE__*/React.createElement("div", {
        style: {
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center'
        }
      }, /*#__PURE__*/React.createElement("span", {
        style: {
          width: 11,
          height: 11,
          borderRadius: 3,
          background: (M.domains.find(function (d) {
            return d.key === g.node.dom;
          }) || {}).col || HB.accent,
          marginTop: 5
        }
      }), gi < groups.length - 1 && /*#__PURE__*/React.createElement("span", {
        style: {
          flex: 1,
          width: 1.5,
          background: HB.line
        }
      })), /*#__PURE__*/React.createElement("div", {
        style: {
          flex: 1,
          paddingBottom: 14
        }
      }, /*#__PURE__*/React.createElement("div", {
        style: {
          fontSize: 12.5,
          fontWeight: 600,
          color: HB.ink
        }
      }, g.node.title), /*#__PURE__*/React.createElement("div", {
        style: {
          fontFamily: HB.mono,
          fontSize: 9,
          color: HB.inkMute,
          marginBottom: 5
        }
      }, (M.domains.find(function (d) {
        return d.key === g.node.dom;
      }) || {}).title), /*#__PURE__*/React.createElement("div", {
        style: {
          display: 'flex',
          flexDirection: 'column',
          gap: 3,
          borderLeft: "1.5px solid ".concat(HB.lineSoft),
          paddingLeft: 9
        }
      }, g.runs.slice(0, 5).map(function (r) {
        return /*#__PURE__*/React.createElement("div", {
          key: r.id,
          style: {
            display: 'flex',
            alignItems: 'center',
            gap: 7
          }
        }, /*#__PURE__*/React.createElement("span", {
          style: {
            width: 7,
            height: 7,
            borderRadius: '50%',
            background: r.ok ? HB.green : HB.red,
            flexShrink: 0
          }
        }), /*#__PURE__*/React.createElement("span", {
          style: {
            fontFamily: HB.mono,
            fontSize: 10.5,
            color: HB.inkSoft
          }
        }, r.variantOf ? '⌥ variant' : 'run', " #", r.n), /*#__PURE__*/React.createElement("span", {
          style: {
            fontFamily: HB.mono,
            fontSize: 9.5,
            color: HB.inkMute,
            marginLeft: 'auto'
          }
        }, ago(r.t), " ago"));
      }))));
    });
  }()))));
}

// ─────────────────────────────────────────────────────────────────────────────
// LIBRARY — the left rail's primary drag source, mirroring Studio's NodesPanel:
// searchable, collapsible categories, drag an item onto the map to create it.
// Same gesture in the cockpit as in the app: the graph logic is one concept.
// ─────────────────────────────────────────────────────────────────────────────
var LIB_GROUPS = [{
  cat: 'connector',
  label: 'HOSTS · CONNECTORS',
  items: [['Revit', 'open doc · view · selection'], ['Rhino / Grasshopper', 'geometry · definition'], ['IFC / Speckle', 'federated exchange'], ['Navisworks', 'clash · appended model']]
}, {
  cat: 'input',
  label: 'READ · INPUT',
  items: [['Parameter read', 'element → value'], ['Schedule read', 'tabular extract'], ['Sheet index', 'sheets · revisions'], ['Model health', 'warnings · file size']]
}, {
  cat: 'transform',
  label: 'TRANSFORM',
  items: [['Map values', 'per-element rewrite'], ['Join / merge', 'two streams → one'], ['Units convert', 'metric ↔ imperial'], ['Classify', 'assign Uniclass / OmniClass']]
}, {
  cat: 'logic',
  label: 'LOGIC',
  items: [['Filter', 'predicate → subset'], ['Branch', 'route by condition'], ['Gate', 'hold until approved'], ['Loop', 'iterate a collection']]
}, {
  cat: 'ai',
  label: 'AI · AGENTS',
  items: [['Agent', 'model + tools + brief'], ['Intent', 'natural language → plan'], ['Review', 'critique against a rule'], ['Summarise', 'stream → digest']]
}, {
  cat: 'skill',
  label: 'SKILLS',
  items: [['Saved field', 'a field you promoted'], ['Saved canvas', 'a whole workflow'], ['Shared skill', 'from the marketplace']]
}, {
  cat: 'watch',
  label: 'WATCH · OUTPUT',
  items: [['Watcher', 'observe a value live'], ['Preview', 'render the data'], ['Publish', 'write back to host'], ['Notify', 'alert a person or channel']]
}];
function LibraryPanel(_ref1) {
  var onCreateNode = _ref1.onCreateNode,
    onAddDomain = _ref1.onAddDomain,
    flash = _ref1.flash;
  var _React$useState7 = React.useState(''),
    _React$useState8 = _slicedToArray(_React$useState7, 2),
    q = _React$useState8[0],
    setQ = _React$useState8[1];
  var _React$useState9 = React.useState(function () {
      return Object.fromEntries(LIB_GROUPS.map(function (g) {
        return [g.cat, true];
      }));
    }),
    _React$useState0 = _slicedToArray(_React$useState9, 2),
    open = _React$useState0[0],
    setOpen = _React$useState0[1];
  var ql = q.trim().toLowerCase();
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      minHeight: 0,
      height: '100%'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      padding: '11px 12px 9px',
      borderBottom: "1px solid ".concat(HB.lineSoft),
      flexShrink: 0
    }
  }, /*#__PURE__*/React.createElement("input", {
    value: q,
    onChange: function onChange(e) {
      return setQ(e.target.value);
    },
    placeholder: "search the library\u2026",
    style: {
      width: '100%',
      padding: '7px 9px',
      borderRadius: 7,
      border: "1px solid ".concat(HB.line),
      background: HB.paper,
      color: HB.ink,
      fontFamily: HB.mono,
      fontSize: 11,
      outline: 'none'
    }
  }), /*#__PURE__*/React.createElement("button", {
    onClick: onAddDomain,
    style: {
      marginTop: 8,
      width: '100%',
      padding: '8px 0',
      borderRadius: 7,
      border: "1px dashed ".concat(HB.accent),
      background: 'transparent',
      color: HB.accent,
      cursor: 'pointer',
      fontFamily: HB.mono,
      fontSize: 10.5,
      letterSpacing: '0.08em'
    }
  }, "\uFF0B NEW DOMAIN")), /*#__PURE__*/React.createElement("div", {
    className: "hb-scroll",
    style: {
      flex: 1,
      overflowY: 'auto',
      overflowX: 'hidden',
      padding: '6px 8px 14px',
      minHeight: 0
    }
  }, LIB_GROUPS.map(function (g) {
    var items = ql ? g.items.filter(function (_ref10) {
      var _ref11 = _slicedToArray(_ref10, 2),
        t = _ref11[0],
        s = _ref11[1];
      return (t + ' ' + s).toLowerCase().includes(ql);
    }) : g.items;
    if (!items.length) return null;
    var col = window.catCol && window.catCol(g.cat) || HB.accent;
    var isOpen = ql ? true : open[g.cat];
    return /*#__PURE__*/React.createElement("div", {
      key: g.cat,
      style: {
        marginBottom: 6
      }
    }, /*#__PURE__*/React.createElement("button", {
      onClick: function onClick() {
        return setOpen(function (o) {
          return _objectSpread(_objectSpread({}, o), {}, _defineProperty({}, g.cat, !o[g.cat]));
        });
      },
      style: {
        width: '100%',
        display: 'flex',
        alignItems: 'center',
        gap: 7,
        padding: '6px 5px',
        background: 'transparent',
        border: 0,
        cursor: 'pointer',
        color: HB.inkSoft,
        fontFamily: HB.mono,
        fontSize: 9,
        letterSpacing: '0.14em',
        textAlign: 'left'
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        width: 7,
        height: 7,
        borderRadius: 2,
        background: col,
        flexShrink: 0
      }
    }), /*#__PURE__*/React.createElement("span", {
      style: {
        flex: 1
      }
    }, g.label), /*#__PURE__*/React.createElement("span", {
      style: {
        color: HB.inkSoft
      }
    }, items.length, " ", isOpen ? '▾' : '▸')), isOpen && /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        flexDirection: 'column',
        gap: 1,
        paddingLeft: 4
      }
    }, items.map(function (_ref12) {
      var _ref13 = _slicedToArray(_ref12, 2),
        title = _ref13[0],
        sub = _ref13[1];
      return /*#__PURE__*/React.createElement("div", {
        key: title,
        draggable: "true",
        onDragStart: function onDragStart(e) {
          e.dataTransfer.setData('application/x-atlas-node', JSON.stringify({
            cat: g.cat,
            title: title,
            sub: sub
          }));
          e.dataTransfer.effectAllowed = 'copy';
        },
        onDoubleClick: function onDoubleClick() {
          return onCreateNode({
            cat: g.cat,
            title: title,
            sub: sub
          });
        },
        title: "Drag onto the map, or double-click to place",
        style: {
          padding: '6px 8px',
          borderRadius: 5,
          cursor: 'grab',
          userSelect: 'none',
          borderLeft: "2px solid transparent"
        },
        onMouseEnter: function onMouseEnter(e) {
          e.currentTarget.style.background = HB.paper2;
          e.currentTarget.style.borderLeftColor = col;
        },
        onMouseLeave: function onMouseLeave(e) {
          e.currentTarget.style.background = 'transparent';
          e.currentTarget.style.borderLeftColor = 'transparent';
        }
      }, /*#__PURE__*/React.createElement("div", {
        style: {
          fontFamily: HB.sans,
          fontSize: 12,
          color: HB.ink
        }
      }, title), /*#__PURE__*/React.createElement("div", {
        style: {
          fontFamily: HB.mono,
          fontSize: 9,
          color: HB.inkMute,
          marginTop: 1
        }
      }, sub));
    })));
  })));
}
Object.assign(window, {
  AgenticPanel: AgenticPanel,
  LibraryPanel: LibraryPanel
});
