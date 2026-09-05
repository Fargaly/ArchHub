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

// The Sessions lens used to render four hand-written conversations between the founder and
// invented agents, complete with plausible replies. Nothing in them had ever happened. The
// real record of the founder talking to his app is the agent-task queue: each row is an
// instruction the cockpit sent and the answer the app posted back. That is what renders now.
var TASK_TONE = {
  done: 'ok',
  failed: 'err',
  running: 'accent',
  claimed: 'accent',
  queued: 'mute'
};
function taskStamp(row) {
  var s = row.finished_at || row.claimed_at || row.created_at;
  return s ? s * 1000 : null;
}
function AgenticPanel(_ref) {
  var M = _ref.M,
    DB = _ref.DB,
    assign = _ref.assign,
    attention = _ref.attention,
    onGoto = _ref.onGoto,
    onTuneAttention = _ref.onTuneAttention,
    attNode = _ref.attNode,
    setColl = _ref.setColl,
    flash = _ref.flash,
    control = _ref.control,
    tasks = _ref.tasks,
    onRelay = _ref.onRelay,
    onReloadTasks = _ref.onReloadTasks;
  var _React$useState = React.useState('activity'),
    _React$useState2 = _slicedToArray(_React$useState, 2),
    tab = _React$useState2[0],
    setTab = _React$useState2[1];
  var rows = tasks || [];
  var ctl = control || null;

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
  }, [['activity', 'Activity', 'bolt'], ['routing', 'Routing', 'sliders'], ['sessions', 'Sessions', 'agent'], ['history', 'History', 'pulse']].map(function (_ref2) {
    var _ref3 = _slicedToArray(_ref2, 3),
      k = _ref3[0],
      l = _ref3[1],
      ic = _ref3[2];
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
    }, r.result, r.ms ? ' · ' + r.ms + 'ms' : '', " \xB7 ", ago(r.t), " ago")));
  })))), tab === 'routing' && function () {
    var models = DB.models || [];
    var live = models.filter(function (m) {
      return m.status !== 'disabled';
    });
    // task classes present anywhere in the fleet, plus the ones the app always needs
    var classes = _toConsumableArray(new Set(['intent', 'vision', 'compose', 'critique', 'extract', 'fallback', 'offline'].concat(_toConsumableArray(models.flatMap(function (m) {
      return m.tasks || [];
    })))));
    // There used to be a hardcoded monthly call volume per task class here, multiplied by
    // each model's rate into a dollar figure the panel printed as SPEND. No call was ever
    // counted. The cockpit does not meter model usage, so it now shows the routing it can
    // prove and says plainly that no spend has been measured.
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
    var issues = DB.issues || [];
    var openIss = issues.filter(function (i) {
      return i.status !== 'resolved';
    });
    var agents = DB.agents || [];
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
    }, "Reassigning a class rewrites the fleet. The change is saved with your model list.")), /*#__PURE__*/React.createElement("div", {
      style: sideSec
    }, /*#__PURE__*/React.createElement("div", {
      style: sideLabel
    }, "SPEND"), /*#__PURE__*/React.createElement("div", {
      style: {
        fontFamily: HB.serif,
        fontStyle: 'italic',
        fontSize: 13,
        color: HB.inkSoft,
        lineHeight: 1.5
      }
    }, "Not measured. Nothing here counts model calls, so the cockpit has no spend figure to give you."), /*#__PURE__*/React.createElement("div", {
      style: {
        fontFamily: HB.mono,
        fontSize: 9.5,
        color: HB.inkMute,
        marginTop: 7,
        lineHeight: 1.5
      }
    }, "Rates you entered per model are shown with each model; a total needs real usage, and usage is not reported to the cloud.")), /*#__PURE__*/React.createElement("div", {
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
    style: _objectSpread(_objectSpread({}, sideLabel), {}, {
      display: 'flex',
      justifyContent: 'space-between'
    })
  }, /*#__PURE__*/React.createElement("span", null, "WHAT YOU ASKED YOUR APP"), /*#__PURE__*/React.createElement("button", {
    onClick: function onClick() {
      return onReloadTasks && onReloadTasks();
    },
    style: {
      border: "1px solid ".concat(HB.line),
      background: 'transparent',
      color: HB.inkSoft,
      borderRadius: 5,
      padding: '2px 7px',
      cursor: 'pointer',
      fontFamily: HB.mono,
      fontSize: 9
    }
  }, "refresh")), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: HB.mono,
      fontSize: 9,
      color: HB.inkMute,
      marginBottom: 10,
      lineHeight: 1.5
    }
  }, "Every instruction the cockpit queued for your ArchHub app, and the answer it posted back."), rows.length === 0 && /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: HB.serif,
      fontStyle: 'italic',
      fontSize: 13,
      color: HB.inkMute
    }
  }, "No instructions yet. Ask the cockpit something and the exchange lands here."), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 8
    }
  }, rows.slice(0, 24).map(function (r) {
    var tone = {
      ok: HB.green,
      err: HB.red,
      accent: HB.accent,
      mute: HB.inkMute
    }[TASK_TONE[r.status] || 'mute'];
    var at = taskStamp(r);
    return /*#__PURE__*/React.createElement("div", {
      key: r.id,
      style: {
        border: "1px solid ".concat(HB.line),
        borderLeft: "3px solid ".concat(tone),
        borderRadius: 10,
        overflow: 'hidden',
        background: HB.card
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        padding: '9px 11px'
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 12.5,
        color: HB.ink,
        lineHeight: 1.45
      }
    }, r.directive), /*#__PURE__*/React.createElement("div", {
      style: {
        fontFamily: HB.mono,
        fontSize: 9.5,
        color: HB.inkMute,
        marginTop: 4
      }
    }, r.status, r.claimed_by ? ' · ' + r.claimed_by : '', at ? ' · ' + ago(at) + ' ago' : '')), r.result ? /*#__PURE__*/React.createElement("div", {
      style: {
        borderTop: "1px solid ".concat(HB.lineSoft),
        padding: '9px 11px',
        background: HB.paper2,
        fontSize: 12,
        color: HB.ink,
        lineHeight: 1.5,
        whiteSpace: 'pre-wrap'
      }
    }, r.result) : /*#__PURE__*/React.createElement("div", {
      style: {
        borderTop: "1px solid ".concat(HB.lineSoft),
        padding: '7px 11px',
        background: HB.paper2,
        fontFamily: HB.serif,
        fontStyle: 'italic',
        fontSize: 12.5,
        color: HB.inkMute
      }
    }, r.status === 'queued' ? 'Waiting for your app to claim it.' : 'No answer posted.'));
  }))), ctl && (ctl.agents || []).length > 0 && /*#__PURE__*/React.createElement("div", {
    style: _objectSpread(_objectSpread({}, sideSec), {}, {
      borderBottom: 'none'
    })
  }, /*#__PURE__*/React.createElement("div", {
    style: sideLabel
  }, "AGENTS YOUR APP REPORTED"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 5
    }
  }, (ctl.agents || []).map(function (a, i) {
    return /*#__PURE__*/React.createElement("div", {
      key: i,
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        padding: '7px 9px',
        borderRadius: 7,
        background: HB.paper2,
        border: "1px solid ".concat(HB.lineSoft)
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        width: 7,
        height: 7,
        borderRadius: '50%',
        flexShrink: 0,
        background: a.status === 'online' ? HB.green : HB.inkMute
      }
    }), /*#__PURE__*/React.createElement("span", {
      style: {
        flex: 1,
        minWidth: 0,
        fontSize: 12,
        color: HB.ink
      }
    }, a.provider || a.runtime || 'agent'), /*#__PURE__*/React.createElement("span", {
      style: {
        fontFamily: HB.mono,
        fontSize: 9.5,
        color: HB.inkMute
      }
    }, String(a.session || '').slice(0, 8)));
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
function LibraryPanel(_ref4) {
  var onCreateNode = _ref4.onCreateNode,
    onAddDomain = _ref4.onAddDomain,
    flash = _ref4.flash;
  var _React$useState3 = React.useState(''),
    _React$useState4 = _slicedToArray(_React$useState3, 2),
    q = _React$useState4[0],
    setQ = _React$useState4[1];
  var _React$useState5 = React.useState(function () {
      return Object.fromEntries(LIB_GROUPS.map(function (g) {
        return [g.cat, true];
      }));
    }),
    _React$useState6 = _slicedToArray(_React$useState5, 2),
    open = _React$useState6[0],
    setOpen = _React$useState6[1];
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
    var items = ql ? g.items.filter(function (_ref5) {
      var _ref6 = _slicedToArray(_ref5, 2),
        t = _ref6[0],
        s = _ref6[1];
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
    }, items.map(function (_ref7) {
      var _ref8 = _slicedToArray(_ref7, 2),
        title = _ref8[0],
        sub = _ref8[1];
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
