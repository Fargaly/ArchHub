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

// He drew a composer under the sessions: you type to your app and the
// exchange lands in the same list. The panel was handed the relay and never
// used it, so the sidebar could only watch (2026-09-07). This sends through
// the same door the ask bar uses and refreshes the list on the answer.
function SessionComposer(_ref) {
  var onRelay = _ref.onRelay,
    onReloadTasks = _ref.onReloadTasks,
    flash = _ref.flash;
  var _React$useState = React.useState(''),
    _React$useState2 = _slicedToArray(_React$useState, 2),
    draft = _React$useState2[0],
    setDraft = _React$useState2[1];
  var _React$useState3 = React.useState(false),
    _React$useState4 = _slicedToArray(_React$useState3, 2),
    busy = _React$useState4[0],
    setBusy = _React$useState4[1];
  var send = function send() {
    var said = draft.trim();
    if (!said || busy || !onRelay) return;
    setBusy(true);
    Promise.resolve(onRelay(said, true)).then(function (d) {
      var text = String(d && d.message || '').slice(0, 160);
      if (flash) flash(text || 'Sent to your app');
      setDraft('');
      if (onReloadTasks) onReloadTasks();
    })["catch"](function (e) {
      if (flash) flash('Not sent: ' + String(e && e.message || e).slice(0, 120));
    }).then(function () {
      return setBusy(false);
    });
  };
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 6,
      marginTop: 10
    }
  }, /*#__PURE__*/React.createElement("input", {
    value: draft,
    onChange: function onChange(e) {
      return setDraft(e.target.value);
    },
    onKeyDown: function onKeyDown(e) {
      if (e.key === 'Enter') send();
    },
    placeholder: busy ? 'Sending…' : 'Message your app…',
    style: {
      flex: 1,
      padding: '7px 10px',
      borderRadius: 8,
      border: '1px solid ' + HB.line,
      background: HB.card,
      color: HB.ink,
      fontSize: 12,
      outline: 'none',
      fontFamily: HB.sans
    }
  }), /*#__PURE__*/React.createElement("button", {
    onClick: send,
    disabled: busy || !draft.trim(),
    style: {
      border: '1px solid ' + HB.line,
      background: draft.trim() && !busy ? HB.accent : 'transparent',
      color: draft.trim() && !busy ? '#fff' : HB.inkMute,
      borderRadius: 8,
      padding: '0 12px',
      cursor: draft.trim() && !busy ? 'pointer' : 'default',
      fontFamily: HB.mono,
      fontSize: 10
    }
  }, "send"));
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
    flash = _ref2.flash,
    control = _ref2.control,
    tasks = _ref2.tasks,
    tasksLoaded = _ref2.tasksLoaded,
    serverErrors = _ref2.serverErrors,
    onRelay = _ref2.onRelay,
    onReloadTasks = _ref2.onReloadTasks;
  var _React$useState5 = React.useState('activity'),
    _React$useState6 = _slicedToArray(_React$useState5, 2),
    tab = _React$useState6[0],
    setTab = _React$useState6[1];
  var _React$useState7 = React.useState({}),
    _React$useState8 = _slicedToArray(_React$useState7, 2),
    openRows = _React$useState8[0],
    setOpenRows = _React$useState8[1]; // session cards the founder folded open or shut
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
    }, ags[0] ? ags[0].name : r.app ? 'Your app' : 'System'), " ran ", /*#__PURE__*/React.createElement("span", {
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
    // MODEL ROUTING shows what the app publishes with its map: control.models and
    // control.routes (the contract is published_models_form in nodelang/cloud_relay.py).
    // This panel used to route task classes over a model list kept in this page that
    // nothing filled, and told the founder a change reached the fleet when no router saw it.
    // Until the app publishes, it says so; a route is changed in the app, not here.
    var published = ctl && Array.isArray(ctl.models) ? ctl.models : null;
    var routes = ctl && Array.isArray(ctl.routes) ? ctl.routes : [];
    // INCIDENTS are the failures the cloud holds: instructions your app answered with a
    // refusal or an error (failed task rows), and server errors since the cloud last
    // restarted. Identical failures fold into one row that carries their real count.
    var fold = function fold(items) {
      var byKey = new Map();
      items.forEach(function (it) {
        var was = byKey.get(it.key);
        if (was) {
          was.count += 1;
          was.t = Math.max(was.t || 0, it.t || 0);
        } else byKey.set(it.key, _objectSpread(_objectSpread({}, it), {}, {
          count: 1
        }));
      });
      return _toConsumableArray(byKey.values()).sort(function (a, b) {
        return (b.t || 0) - (a.t || 0);
      });
    };
    var errorsLoaded = !!(serverErrors && serverErrors.loaded);
    var failed = tasksLoaded ? rows.filter(function (r) {
      return r.status === 'failed';
    }).map(function (r) {
      return {
        key: 'task:' + r.directive,
        source: 'your app',
        title: String(r.directive || 'instruction'),
        detail: String(r.result || ''),
        t: taskStamp(r)
      };
    }) : [];
    var serverRows = errorsLoaded ? (serverErrors.rows || []).map(function (e) {
      return {
        key: 'error:' + e.where + ':' + e.kind,
        source: 'cloud',
        title: String(e.kind || 'error') + " \xB7 " + String(e.where || ''),
        detail: String(e.message || ''),
        t: e.ts ? e.ts * 1000 : null
      };
    }) : [];
    var incidents = fold([].concat(_toConsumableArray(failed), _toConsumableArray(serverRows)));
    var events = incidents.reduce(function (n, it) {
      return n + it.count;
    }, 0);
    var known = !!tasksLoaded || errorsLoaded;
    var clearText = [tasksLoaded ? 'Nothing failed in the last ' + rows.length + ' instruction' + (rows.length === 1 ? '' : 's') : 'The task queue could not be read', errorsLoaded ? 'the cloud has recorded no server error since it last restarted' : 'the cloud error log could not be read'].join('; ') + '.';
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
    }, published ? published.length + ' model' + (published.length === 1 ? '' : 's') : 'not published')), !published && /*#__PURE__*/React.createElement("div", {
      style: {
        fontFamily: HB.serif,
        fontStyle: 'italic',
        fontSize: 13,
        color: HB.inkMute,
        lineHeight: 1.5
      }
    }, "Your app has not published its model list, so there is no routing to show. It appears here once the app sends it with the map."), published && published.length === 0 && /*#__PURE__*/React.createElement("div", {
      style: {
        fontFamily: HB.serif,
        fontStyle: 'italic',
        fontSize: 13,
        color: HB.inkMute
      }
    }, "Your app published an empty model list."), published && published.length > 0 && /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        flexDirection: 'column',
        gap: 5
      }
    }, published.map(function (m, i) {
      return /*#__PURE__*/React.createElement("div", {
        key: m.name + ':' + i,
        style: {
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          padding: '6px 9px',
          borderRadius: 7,
          background: HB.paper2,
          border: '1px solid ' + HB.lineSoft
        }
      }, /*#__PURE__*/React.createElement("span", {
        style: {
          width: 7,
          height: 7,
          borderRadius: '50%',
          flexShrink: 0,
          background: m.available ? HB.green : HB.inkMute
        }
      }), /*#__PURE__*/React.createElement("span", {
        style: {
          flex: 1,
          minWidth: 0,
          fontSize: 12,
          color: HB.ink,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap'
        }
      }, m.name), /*#__PURE__*/React.createElement("span", {
        style: {
          fontFamily: HB.mono,
          fontSize: 9.5,
          color: HB.inkMute
        }
      }, m.provider, m.available ? '' : " \xB7 unavailable"));
    })), published && routes.length > 0 && /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        flexDirection: 'column',
        gap: 4,
        marginTop: 10
      }
    }, routes.map(function (r) {
      return /*#__PURE__*/React.createElement("div", {
        key: r.task,
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
      }, r.task), /*#__PURE__*/React.createElement("span", {
        style: {
          flex: 1,
          minWidth: 0,
          fontFamily: HB.mono,
          fontSize: 10,
          color: HB.inkSoft,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap'
        }
      }, r.model));
    })), published && /*#__PURE__*/React.createElement("div", {
      style: {
        fontFamily: HB.mono,
        fontSize: 9,
        color: HB.inkSoft,
        marginTop: 9,
        lineHeight: 1.5
      }
    }, routes.length ? 'Routing as your app reported it. Change it in the app.' : 'Your app did not report which model serves each task.')), /*#__PURE__*/React.createElement("div", {
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
    }, "Not measured. Nothing here counts model calls, so the cockpit has no spend figure to give you.")), /*#__PURE__*/React.createElement("div", {
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
        color: !known ? HB.inkMute : events ? HB.red : HB.green
      }
    }, !known ? 'not known' : events ? events + ' recorded' : 'none recorded')), !known && /*#__PURE__*/React.createElement("div", {
      style: {
        fontFamily: HB.serif,
        fontStyle: 'italic',
        fontSize: 13,
        color: HB.inkMute,
        lineHeight: 1.5
      }
    }, "The cockpit could not read the task queue or the cloud error log, so it cannot tell whether anything failed."), known && incidents.length === 0 && /*#__PURE__*/React.createElement("div", {
      style: {
        fontFamily: HB.serif,
        fontStyle: 'italic',
        fontSize: 13,
        color: HB.inkSoft,
        lineHeight: 1.5
      }
    }, clearText), /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        flexDirection: 'column',
        gap: 6
      }
    }, incidents.slice(0, 8).map(function (it) {
      return /*#__PURE__*/React.createElement("div", {
        key: it.key,
        title: it.detail,
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
          background: HB.red,
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
      }, "\xD7" + it.count)), /*#__PURE__*/React.createElement("div", {
        style: {
          fontFamily: HB.mono,
          fontSize: 9.5,
          color: HB.inkMute,
          marginTop: 5,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap'
        }
      }, it.source, it.t ? " \xB7 " + ago(it.t) + ' ago' : '', it.detail ? " \xB7 " + it.detail : ''));
    }), incidents.length > 8 && /*#__PURE__*/React.createElement("div", {
      style: {
        fontFamily: HB.mono,
        fontSize: 9.5,
        color: HB.inkMute
      }
    }, incidents.length - 8, " more not shown"))));
  }(), tab === 'sessions' && /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: _objectSpread(_objectSpread({}, sideSec), {}, {
      borderBottom: "1px solid ".concat(HB.line)
    })
  }, /*#__PURE__*/React.createElement("div", {
    style: _objectSpread(_objectSpread({}, sideLabel), {}, {
      display: 'flex',
      justifyContent: 'space-between'
    })
  }, /*#__PURE__*/React.createElement("span", null, "CONVERSATIONS WITH YOUR AGENTS"), /*#__PURE__*/React.createElement("button", {
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
  }, "What you said to your app, and what it said back. Type below to say something new."), rows.length === 0 && /*#__PURE__*/React.createElement("div", {
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
  }, rows.slice(0, 24).map(function (r, i) {
    var tone = {
      ok: HB.green,
      err: HB.red,
      accent: HB.accent,
      mute: HB.inkMute
    }[TASK_TONE[r.status] || 'mute'];
    var at = taskStamp(r);
    // His card: each exchange is a card that folds open to the conversation
    // inside it, and the newest opens by itself as the first card did in his
    // design. The rows are still the real task queue; nothing here is seeded.
    var open = openRows[r.id] !== undefined ? openRows[r.id] : i === 0;
    return /*#__PURE__*/React.createElement("div", {
      key: r.id,
      style: {
        border: "1px solid ".concat(HB.line),
        borderRadius: 10,
        overflow: 'hidden',
        background: HB.card
      }
    }, /*#__PURE__*/React.createElement("button", {
      onClick: function onClick() {
        return setOpenRows(function (o) {
          return _objectSpread(_objectSpread({}, o), {}, _defineProperty({}, r.id, !open));
        });
      },
      "aria-expanded": open,
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
    }, r.directive), /*#__PURE__*/React.createElement("span", {
      style: {
        fontFamily: HB.mono,
        fontSize: 9.5,
        color: HB.inkMute
      }
    }, r.claimed_by || 'your app', at ? " \xB7 " + ago(at) + ' ago' : '')), /*#__PURE__*/React.createElement("span", {
      title: r.status,
      style: {
        width: 7,
        height: 7,
        borderRadius: '50%',
        flexShrink: 0,
        background: tone
      }
    }), /*#__PURE__*/React.createElement("span", {
      style: {
        fontFamily: HB.mono,
        fontSize: 15,
        color: HB.inkMute,
        width: 14,
        textAlign: 'center'
      }
    }, open ? "\u25BE" : "\u25B8")), open &&
    /*#__PURE__*/
    // His treatment inside the card: what the founder said sits right in an
    // accent bubble with its state under it, what the app answered sits left
    // in a bordered card, both capped so the exchange reads as a conversation.
    React.createElement("div", {
      style: {
        borderTop: "1px solid ".concat(HB.lineSoft),
        padding: '10px 11px',
        display: 'flex',
        flexDirection: 'column',
        gap: 6,
        background: HB.paper2
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        flexDirection: 'row-reverse',
        gap: 8
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        maxWidth: '82%',
        padding: '7px 10px',
        borderRadius: 10,
        fontSize: 12,
        lineHeight: 1.45,
        background: HB.accent,
        color: '#fff'
      }
    }, r.directive)), /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        flexDirection: 'row-reverse',
        gap: 8
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        fontFamily: HB.mono,
        fontSize: 9.5,
        color: tone
      }
    }, r.status)), /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        flexDirection: 'row',
        gap: 8
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        maxWidth: '82%',
        padding: '7px 10px',
        borderRadius: 10,
        fontSize: 12,
        lineHeight: 1.5,
        background: HB.card,
        color: r.result ? HB.ink : HB.inkMute,
        border: "1px solid ".concat(HB.line),
        whiteSpace: 'pre-wrap',
        fontFamily: r.result ? HB.sans : HB.serif,
        fontStyle: r.result ? 'normal' : 'italic'
      }
    }, r.result || (r.status === 'queued' ? 'Waiting for your app to claim it.' : 'No answer posted.')))));
  })), /*#__PURE__*/React.createElement(SessionComposer, {
    onRelay: onRelay,
    onReloadTasks: onReloadTasks,
    flash: flash
  })), ctl && (ctl.agents || []).length > 0 && /*#__PURE__*/React.createElement("div", {
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
// The COCKPIT library. It held the desktop studio's node palette -- Revit,
// Rhino, IFC, parameter reads -- which do nothing here: the founder asked
// what a Revit host node would even do in the cockpit (2026-09-07). The
// cockpit is where he runs the business and directs the agents, so its
// library is the work he actually places on this map. Host and geometry
// nodes stay in the studio, on the canvas that can run them.
var LIB_GROUPS = [{
  cat: 'ai',
  label: 'AGENTS',
  items: [['Agent', 'a runtime that claims Work'], ['Assignment', 'give this to an agent'], ['Review', 'an agent critiques the result'], ['Handoff', 'pass Work between agents']]
}, {
  cat: 'logic',
  label: 'WORK',
  items: [['Work item', 'something to be done'], ['Gate', 'hold until approved'], ['Court', 'the check that proves it'], ['Blocker', 'why it cannot proceed']]
}, {
  cat: 'input',
  label: 'BRAIN',
  items: [['Recall', 'ask the brain a question'], ['Remember', 'commit a fact'], ['Fact', 'one thing the brain holds'], ['Digest', 'summarise a stream']]
}, {
  cat: 'watch',
  label: 'WATCH',
  items: [['Metric', 'a number to follow'], ['Alert', 'tell me when it moves'], ['Report', 'a view assembled on demand'], ['Log', 'what happened, in order']]
}, {
  cat: 'transform',
  label: 'MAP',
  items: [['Domain', 'a place on this map'], ['Field', 'a domain of domains'], ['Capability', 'something the product does'], ['Wire', 'this depends on that']]
}, {
  cat: 'connector',
  label: 'REACH',
  items: [['Host', 'an application on a machine'], ['Cloud service', 'something running remotely'], ['Person', 'someone who is told'], ['Schedule', 'when it runs by itself']]
}];
function LibraryPanel(_ref5) {
  var onCreateNode = _ref5.onCreateNode,
    onAddDomain = _ref5.onAddDomain,
    flash = _ref5.flash;
  var _React$useState9 = React.useState(''),
    _React$useState0 = _slicedToArray(_React$useState9, 2),
    q = _React$useState0[0],
    setQ = _React$useState0[1];
  var _React$useState1 = React.useState(function () {
      return Object.fromEntries(LIB_GROUPS.map(function (g) {
        return [g.cat, true];
      }));
    }),
    _React$useState10 = _slicedToArray(_React$useState1, 2),
    open = _React$useState10[0],
    setOpen = _React$useState10[1];
  var _React$useState11 = React.useState(null),
    _React$useState12 = _slicedToArray(_React$useState11, 2),
    ghost = _React$useState12[0],
    setGhost = _React$useState12[1];
  var ql = q.trim().toLowerCase();
  // POINTER drag, not HTML5 drag-and-drop. The founder could not drag a node
  // onto the canvas at all: QtWebEngine does not carry an HTML5 drag reliably
  // inside the desktop shell, and a drag that never starts leaves no error to
  // read (2026-09-07). Pointer capture works in every shell and gives a real
  // preview of what is being carried.
  var startLibraryDrag = function startLibraryDrag(event, item, col) {
    if (event.button !== 0) return;
    var from = {
      x: event.clientX,
      y: event.clientY
    };
    var carrying = false;
    var move = function move(moved) {
      if (!carrying) {
        if (Math.abs(moved.clientX - from.x) + Math.abs(moved.clientY - from.y) < 5) return;
        carrying = true;
      }
      setGhost({
        item: item,
        col: col,
        x: moved.clientX,
        y: moved.clientY
      });
    };
    var _up = function up(ended) {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', _up);
      window.removeEventListener('pointercancel', _up);
      setGhost(null);
      if (!carrying) return;
      var drop = window.__atlasDropLibraryItem;
      var landed = drop && drop(item, ended.clientX, ended.clientY);
      if (!landed && flash) flash('Drop it on the map to place ' + item.title);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', _up);
    window.addEventListener('pointercancel', _up);
  };
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
  }, "\uFF0B NEW DOMAIN")), ghost && /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'fixed',
      left: ghost.x + 12,
      top: ghost.y + 10,
      zIndex: 9999,
      pointerEvents: 'none',
      padding: '6px 10px',
      borderRadius: 6,
      background: HB.paper2,
      color: HB.ink,
      border: "1px solid ".concat(ghost.col),
      borderLeft: "3px solid ".concat(ghost.col),
      boxShadow: '0 8px 22px rgba(0,0,0,.35)',
      fontFamily: HB.sans,
      fontSize: 12,
      whiteSpace: 'nowrap'
    }
  }, ghost.item.title), /*#__PURE__*/React.createElement("div", {
    className: "hb-scroll",
    style: {
      flex: 1,
      overflowY: 'auto',
      overflowX: 'hidden',
      padding: '6px 8px 14px',
      minHeight: 0
    }
  }, LIB_GROUPS.map(function (g) {
    var items = ql ? g.items.filter(function (_ref6) {
      var _ref7 = _slicedToArray(_ref6, 2),
        t = _ref7[0],
        s = _ref7[1];
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
    }, items.map(function (_ref8) {
      var _ref9 = _slicedToArray(_ref8, 2),
        title = _ref9[0],
        sub = _ref9[1];
      return /*#__PURE__*/React.createElement("div", {
        key: title,
        onPointerDown: function onPointerDown(e) {
          return startLibraryDrag(e, {
            cat: g.cat,
            title: title,
            sub: sub
          }, col);
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
