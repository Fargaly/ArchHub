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
// atlas-panels.jsx — the permanent RIGHT panel states (macro / micro / bulk) + modals.
// Macro: overview + create domain/node + groups. Micro: node inspector. Bulk: multi-select ops.

var _window = window,
  HB = _window.HB,
  hsc = _window.hsc,
  HBtn = _window.HBtn,
  HIconBtn = _window.HIconBtn,
  HPill = _window.HPill,
  HDot = _window.HDot,
  HAvatar = _window.HAvatar,
  STC = _window.STC,
  catCol = _window.catCol;
var insLabel = {
  fontFamily: HB.mono,
  fontSize: 8.5,
  color: HB.accent,
  fontWeight: 700,
  letterSpacing: '0.14em',
  marginBottom: 7
};
var insInput = function insInput(mono) {
  return {
    width: '100%',
    background: HB.paper2,
    border: "1px solid ".concat(HB.line),
    color: HB.ink,
    borderRadius: 7,
    padding: '8px 10px',
    fontSize: 12.5,
    fontFamily: mono ? HB.mono : HB.sans,
    outline: 'none',
    resize: 'vertical'
  };
};
var secStyle = {
  padding: '15px 16px',
  borderBottom: "1px solid ".concat(HB.lineSoft)
};

/* ════ SYSTEM — macro, nothing selected: whole-system overview ════ */
function SystemPanel(_ref) {
  var M = _ref.M,
    counts = _ref.counts,
    total = _ref.total,
    STATUS = _ref.STATUS,
    attention = _ref.attention,
    onGoto = _ref.onGoto,
    onAddDomain = _ref.onAddDomain,
    onEnter = _ref.onEnter,
    openRoom = _ref.openRoom;
  var domOf = {};
  M.nodes.forEach(function (n) {
    return domOf[n.id] = n.dom;
  });
  var cross = 0;
  M.wires.forEach(function (w) {
    if (domOf[w.a] && domOf[w.b] && domOf[w.a] !== domOf[w.b]) cross++;
  });
  var toneCol = {
    red: HB.red,
    accent: HB.accent,
    blue: HB.blue,
    green: HB.green
  };
  var toneIcon = {
    blocked: 'x',
    gap: 'eye',
    agent: 'agent'
  };
  return /*#__PURE__*/React.createElement("div", null, attention && attention.length > 0 && /*#__PURE__*/React.createElement("div", {
    style: _objectSpread(_objectSpread({}, secStyle), {}, {
      borderBottom: "1px solid ".concat(HB.line),
      background: HB.paper2
    })
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 7,
      marginBottom: 10
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
      letterSpacing: '0.18em'
    }
  }, "WHAT MATTERS NOW")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 6
    }
  }, attention.map(function (it, i) {
    var c = toneCol[it.tone];
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
      name: toneIcon[it.kind],
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
    }, it.sub)), /*#__PURE__*/React.createElement(CKIcon, {
      name: "eye",
      size: 13,
      color: HB.inkMute
    }));
  }))), /*#__PURE__*/React.createElement("div", {
    style: _objectSpread(_objectSpread({}, secStyle), {}, {
      borderBottom: "1px solid ".concat(HB.line)
    })
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: HB.mono,
      fontSize: 8.5,
      color: HB.accent,
      letterSpacing: '0.2em'
    }
  }, "MACRO \xB7 THE WHOLE SYSTEM"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: HB.serif,
      fontSize: 24,
      letterSpacing: '-0.02em',
      marginTop: 2
    }
  }, M.domains.length, " domains, wired"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: HB.mono,
      fontSize: 11,
      color: HB.inkSoft,
      marginTop: 6,
      lineHeight: 1.5
    }
  }, total, " capabilities \xB7 ", M.wires.length, " wires \xB7 ", cross, " cross-domain links. Hover a domain to trace its links; double-click to open.")), /*#__PURE__*/React.createElement("div", {
    style: secStyle
  }, /*#__PURE__*/React.createElement("div", {
    style: insLabel
  }, "STATUS ACROSS THE SYSTEM"), STATUS.filter(function (s) {
    return counts[s];
  }).map(function (s) {
    return /*#__PURE__*/React.createElement("div", {
      key: s,
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 9,
        padding: '4px 0'
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        width: 9,
        height: 9,
        borderRadius: 2,
        background: STC[s]
      }
    }), /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 12.5,
        textTransform: 'capitalize',
        flex: 1
      }
    }, s), /*#__PURE__*/React.createElement("span", {
      style: {
        flex: 2,
        height: 6,
        borderRadius: 3,
        background: HB.paper2,
        overflow: 'hidden'
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        display: 'block',
        height: '100%',
        width: "".concat(counts[s] / total * 100, "%"),
        background: STC[s]
      }
    })), /*#__PURE__*/React.createElement("span", {
      style: {
        fontFamily: HB.mono,
        fontSize: 10.5,
        color: HB.inkMute,
        width: 26,
        textAlign: 'right'
      }
    }, counts[s]));
  })));
}

/* ════ DOMAIN — a domain selected (macro) or open (micro) ════ */
function DomainPanel(_ref2) {
  var M = _ref2.M,
    domKey = _ref2.domKey,
    DB = _ref2.DB,
    counts = _ref2.counts,
    STATUS = _ref2.STATUS,
    CATS = _ref2.CATS,
    macro = _ref2.macro,
    patchDomain = _ref2.patchDomain,
    assign = _ref2.assign,
    toggleAgent = _ref2.toggleAgent,
    onEnter = _ref2.onEnter,
    onAddNode = _ref2.onAddNode,
    onUngroup = _ref2.onUngroup,
    openRoom = _ref2.openRoom,
    selectBy = _ref2.selectBy,
    onClose = _ref2.onClose;
  var _React$useState = React.useState('control'),
    _React$useState2 = _slicedToArray(_React$useState, 2),
    tab = _React$useState2[0],
    setTab = _React$useState2[1];
  var d = M.domains.find(function (x) {
    return x.key === domKey;
  }) || {};
  var members = M.nodes.filter(function (n) {
    return n.dom === domKey;
  });
  var ids = new Set(members.map(function (n) {
    return n.id;
  }));
  var intra = M.wires.filter(function (w) {
    return ids.has(w.a) && ids.has(w.b);
  }).length;
  var domOf = {};
  M.nodes.forEach(function (n) {
    return domOf[n.id] = n.dom;
  });
  var ports = {};
  M.wires.forEach(function (w) {
    var other;
    if (ids.has(w.a) && !ids.has(w.b)) other = domOf[w.b];else if (ids.has(w.b) && !ids.has(w.a)) other = domOf[w.a];
    if (other) ports[other] = (ports[other] || 0) + 1;
  });
  var inbound = {},
    outbound = {};
  M.wires.forEach(function (w) {
    var aIn = ids.has(w.a),
      bIn = ids.has(w.b);
    if (aIn && !bIn) outbound[domOf[w.b]] = (outbound[domOf[w.b]] || 0) + 1;else if (bIn && !aIn) inbound[domOf[w.a]] = (inbound[domOf[w.a]] || 0) + 1;
  });
  var ifaceCount = new Set([].concat(_toConsumableArray(Object.keys(inbound)), _toConsumableArray(Object.keys(outbound)))).size;
  var st = {};
  members.forEach(function (n) {
    return st[n.status] = (st[n.status] || 0) + 1;
  });
  var agentCount = members.filter(function (n) {
    return (assign[n.id] || []).length;
  }).length;
  var myAgents = assign[domKey] || [];
  var params = d.params || [];
  var setParam = function setParam(i, k, v) {
    var p = params.map(function (x, j) {
      return j === i ? _objectSpread(_objectSpread({}, x), {}, _defineProperty({}, k, v)) : x;
    });
    patchDomain(domKey, {
      params: p
    });
  };
  var addParam = function addParam() {
    return patchDomain(domKey, {
      params: [].concat(_toConsumableArray(params), [{
        k: 'key',
        v: 'value'
      }])
    });
  };
  var delParam = function delParam(i) {
    return patchDomain(domKey, {
      params: params.filter(function (_, j) {
        return j !== i;
      })
    });
  };
  return /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'sticky',
      top: 0,
      zIndex: 2,
      background: HB.card,
      borderBottom: "1px solid ".concat(HB.line),
      padding: '14px 16px'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'flex-start',
      gap: 10
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: 32,
      height: 32,
      borderRadius: 8,
      display: 'grid',
      placeItems: 'center',
      background: d.col + '22',
      color: d.col,
      flexShrink: 0,
      marginTop: 2
    }
  }, /*#__PURE__*/React.createElement(CKIcon, {
    name: "grid",
    size: 16
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      minWidth: 0
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: HB.mono,
      fontSize: 8.5,
      color: d.col,
      letterSpacing: '0.16em'
    }
  }, d.grouped ? '⊞ GRAND NODE · GROUPED' : 'SUPER-NODE · DOMAIN', " \xB7 ", members.length, " INSIDE"), /*#__PURE__*/React.createElement("input", {
    value: d.title || '',
    onChange: function onChange(e) {
      return patchDomain(domKey, {
        title: e.target.value
      });
    },
    style: {
      width: '100%',
      border: 'none',
      background: 'transparent',
      fontFamily: HB.serif,
      fontSize: 23,
      letterSpacing: '-0.02em',
      color: HB.ink,
      outline: 'none',
      padding: 0,
      marginTop: 2
    }
  })), /*#__PURE__*/React.createElement(HIconBtn, {
    name: "x",
    onClick: onClose
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 8,
      marginTop: 11
    }
  }, /*#__PURE__*/React.createElement(HBtn, {
    primary: true,
    onClick: onEnter,
    style: {
      flex: 1,
      justifyContent: 'center'
    }
  }, /*#__PURE__*/React.createElement(CKIcon, {
    name: "eye",
    size: 13
  }), "Open"), /*#__PURE__*/React.createElement(HBtn, {
    onClick: onAddNode,
    style: {
      flex: 1,
      justifyContent: 'center'
    }
  }, /*#__PURE__*/React.createElement(CKIcon, {
    name: "plus",
    size: 13
  }), "Add node"), d.grouped && onUngroup && /*#__PURE__*/React.createElement(HBtn, {
    onClick: function onClick() {
      return onUngroup(domKey);
    },
    style: {
      flex: 1,
      justifyContent: 'center'
    }
  }, /*#__PURE__*/React.createElement(CKIcon, {
    name: "grid",
    size: 13
  }), "Ungroup")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 4,
      marginTop: 11
    }
  }, [['control', 'Control'], ['params', "Params ".concat(params.length)], ['links', "Interface ".concat(ifaceCount)]].map(function (_ref3) {
    var _ref4 = _slicedToArray(_ref3, 2),
      k = _ref4[0],
      l = _ref4[1];
    return /*#__PURE__*/React.createElement("button", {
      key: k,
      onClick: function onClick() {
        return setTab(k);
      },
      style: {
        flex: 1,
        padding: '6px 0',
        borderRadius: 7,
        cursor: 'pointer',
        fontFamily: HB.mono,
        fontSize: 10.5,
        border: "1px solid ".concat(tab === k ? HB.accent : HB.line),
        background: tab === k ? HB.accentSoft : 'transparent',
        color: tab === k ? HB.accentHi : HB.inkSoft
      }
    }, l);
  }))), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: 0
    }
  }, tab === 'control' && /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: secStyle
  }, /*#__PURE__*/React.createElement("div", {
    style: insLabel
  }, "INTENT"), /*#__PURE__*/React.createElement("textarea", {
    value: d.sub || '',
    onChange: function onChange(e) {
      return patchDomain(domKey, {
        sub: e.target.value
      });
    },
    rows: 2,
    placeholder: "What this domain owns\u2026",
    style: insInput()
  })), /*#__PURE__*/React.createElement("div", {
    style: secStyle
  }, /*#__PURE__*/React.createElement("div", {
    style: insLabel
  }, "DOMAIN STATUS \xB7 ROLLS UP TO ROADMAP"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexWrap: 'wrap',
      gap: 5
    }
  }, STATUS.map(function (s) {
    return /*#__PURE__*/React.createElement("button", {
      key: s,
      onClick: function onClick() {
        return patchDomain(domKey, {
          status: s
        });
      },
      style: {
        display: 'inline-flex',
        alignItems: 'center',
        gap: 5,
        padding: '5px 10px',
        borderRadius: 999,
        cursor: 'pointer',
        fontFamily: HB.mono,
        fontSize: 10.5,
        textTransform: 'capitalize',
        border: "1px solid ".concat(d.status === s ? STC[s] : HB.line),
        background: d.status === s ? STC[s] + '20' : 'transparent',
        color: d.status === s ? STC[s] : HB.inkSoft
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        width: 7,
        height: 7,
        borderRadius: 2,
        background: STC[s]
      }
    }), s);
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 7,
      marginTop: 10,
      height: 8
    }
  }, STATUS.filter(function (s) {
    return st[s];
  }).map(function (s) {
    return /*#__PURE__*/React.createElement("span", {
      key: s,
      title: "".concat(s, ": ").concat(st[s]),
      style: {
        flex: st[s],
        background: STC[s],
        height: 8,
        borderRadius: 2
      }
    });
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: HB.mono,
      fontSize: 9.5,
      color: HB.inkMute,
      marginTop: 6
    }
  }, "composition of ", members.length, " nodes \xB7 ", intra, " internal wires")), /*#__PURE__*/React.createElement("div", {
    style: secStyle
  }, /*#__PURE__*/React.createElement("div", {
    style: insLabel
  }, "OWNED BY AGENTS \xB7 WHOLE DOMAIN"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 6
    }
  }, DB.agents.map(function (a) {
    var on = myAgents.includes(a.id);
    return /*#__PURE__*/React.createElement("button", {
      key: a.id,
      onClick: function onClick() {
        return toggleAgent(domKey, a.id);
      },
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 9,
        padding: '8px 10px',
        borderRadius: 8,
        cursor: 'pointer',
        textAlign: 'left',
        border: "1px solid ".concat(on ? HB.accent : HB.line),
        background: on ? HB.accentSoft : HB.paper2
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        position: 'relative',
        flexShrink: 0,
        display: 'grid',
        placeItems: 'center'
      }
    }, /*#__PURE__*/React.createElement(HAvatar, {
      name: a.name,
      size: 26
    }), on && /*#__PURE__*/React.createElement("span", {
      style: {
        position: 'absolute',
        inset: -2,
        borderRadius: '50%',
        border: "2px solid ".concat(HB.accent)
      }
    })), /*#__PURE__*/React.createElement("span", {
      style: {
        flex: 1,
        minWidth: 0
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 12.5,
        fontWeight: 500,
        display: 'block'
      }
    }, a.name), /*#__PURE__*/React.createElement("span", {
      style: {
        fontFamily: HB.mono,
        fontSize: 9.5,
        color: HB.inkMute
      }
    }, (DB.models.find(function (m) {
      return m.id === a.model;
    }) || {}).name)), on ? /*#__PURE__*/React.createElement("span", {
      style: {
        color: HB.accent
      }
    }, /*#__PURE__*/React.createElement(CKIcon, {
      name: "check",
      size: 15
    })) : /*#__PURE__*/React.createElement("span", {
      style: {
        fontFamily: HB.mono,
        fontSize: 9,
        color: HB.inkMute,
        letterSpacing: '0.1em'
      }
    }, "ASSIGN"));
  })), agentCount > 0 && /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: HB.mono,
      fontSize: 10,
      color: HB.accent,
      marginTop: 8
    }
  }, "\u25C7 plus ", agentCount, " member nodes individually owned")), /*#__PURE__*/React.createElement("div", {
    style: secStyle
  }, /*#__PURE__*/React.createElement("div", {
    style: insLabel
  }, "QUICK SELECT INSIDE"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexWrap: 'wrap',
      gap: 6
    }
  }, STATUS.filter(function (s) {
    return st[s];
  }).map(function (s) {
    return /*#__PURE__*/React.createElement("button", {
      key: s,
      onClick: function onClick() {
        return selectBy(function (n) {
          return n.dom === domKey && n.status === s;
        });
      },
      style: chip(STC[s])
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        width: 7,
        height: 7,
        borderRadius: 2,
        background: STC[s]
      }
    }), s, " ", st[s]);
  })))), tab === 'params' && /*#__PURE__*/React.createElement("div", {
    style: secStyle
  }, /*#__PURE__*/React.createElement("div", {
    style: insLabel
  }, "DOMAIN PARAMETERS"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 6
    }
  }, params.length === 0 && /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: HB.serif,
      fontStyle: 'italic',
      fontSize: 13,
      color: HB.inkMute
    }
  }, "No parameters. Add config that governs the whole domain."), params.map(function (p, i) {
    return /*#__PURE__*/React.createElement("div", {
      key: i,
      style: {
        display: 'flex',
        gap: 6
      }
    }, /*#__PURE__*/React.createElement("input", {
      value: p.k,
      onChange: function onChange(e) {
        return setParam(i, 'k', e.target.value);
      },
      style: _objectSpread(_objectSpread({}, insInput(true)), {}, {
        flex: 1,
        fontSize: 11.5
      })
    }), /*#__PURE__*/React.createElement("input", {
      value: p.v,
      onChange: function onChange(e) {
        return setParam(i, 'v', e.target.value);
      },
      style: _objectSpread(_objectSpread({}, insInput(true)), {}, {
        flex: 1.3,
        fontSize: 11.5
      })
    }), /*#__PURE__*/React.createElement("button", {
      onClick: function onClick() {
        return delParam(i);
      },
      style: {
        border: "1px solid ".concat(HB.line),
        background: HB.paper2,
        color: HB.red,
        borderRadius: 6,
        width: 30,
        cursor: 'pointer'
      }
    }, "\u2715"));
  })), /*#__PURE__*/React.createElement(HBtn, {
    small: true,
    onClick: addParam,
    style: {
      marginTop: 10
    }
  }, /*#__PURE__*/React.createElement(CKIcon, {
    name: "plus",
    size: 12
  }), "Add parameter"), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 16
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: insLabel
  }, "EVIDENCE \xB7 FEDERATION"), /*#__PURE__*/React.createElement("input", {
    value: d.evidence_ref || '',
    onChange: function onChange(e) {
      return patchDomain(domKey, {
        evidence_ref: e.target.value
      });
    },
    placeholder: "dir:app/web_ui/\u2026 \xB7 doc:\u2026",
    style: insInput(true)
  }))), tab === 'links' && /*#__PURE__*/React.createElement("div", {
    style: secStyle
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: HB.mono,
      fontSize: 9.5,
      color: HB.inkMute,
      marginBottom: 12,
      lineHeight: 1.5
    }
  }, "The domain's interface \u2014 ports reflected up from its ", members.length, " member nodes' cross-domain wiring."), /*#__PURE__*/React.createElement("div", {
    style: _objectSpread(_objectSpread({}, insLabel), {}, {
      color: HB.blue
    })
  }, "\u25B8 INBOUND PORTS \xB7 fed by (", Object.keys(inbound).length, ")"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 5,
      marginBottom: 16
    }
  }, Object.entries(inbound).sort(function (a, b) {
    return b[1] - a[1];
  }).map(function (_ref5) {
    var _ref6 = _slicedToArray(_ref5, 2),
      k = _ref6[0],
      ct = _ref6[1];
    var dd = M.domains.find(function (x) {
      return x.key === k;
    });
    return /*#__PURE__*/React.createElement("div", {
      key: k,
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 9,
        padding: '7px 10px',
        borderRadius: 7,
        border: "1px solid ".concat(HB.lineSoft),
        background: HB.paper2
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        width: 9,
        height: 9,
        borderRadius: '50%',
        background: dd ? dd.col : HB.inkMute,
        flexShrink: 0
      }
    }), /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 12.5
      }
    }, dd ? dd.title : k), /*#__PURE__*/React.createElement("span", {
      style: {
        marginLeft: 'auto',
        fontFamily: HB.mono,
        fontSize: 11,
        color: HB.blue
      }
    }, ct, " \u2192"));
  }), !Object.keys(inbound).length && /*#__PURE__*/React.createElement(Empty, null, "Nothing feeds this domain.")), /*#__PURE__*/React.createElement("div", {
    style: _objectSpread(_objectSpread({}, insLabel), {}, {
      color: HB.green
    })
  }, "OUTBOUND PORTS \u25B8 \xB7 drives (", Object.keys(outbound).length, ")"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 5
    }
  }, Object.entries(outbound).sort(function (a, b) {
    return b[1] - a[1];
  }).map(function (_ref7) {
    var _ref8 = _slicedToArray(_ref7, 2),
      k = _ref8[0],
      ct = _ref8[1];
    var dd = M.domains.find(function (x) {
      return x.key === k;
    });
    return /*#__PURE__*/React.createElement("div", {
      key: k,
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 9,
        padding: '7px 10px',
        borderRadius: 7,
        border: "1px solid ".concat(HB.lineSoft),
        background: HB.paper2
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        width: 9,
        height: 9,
        borderRadius: '50%',
        background: dd ? dd.col : HB.inkMute,
        flexShrink: 0
      }
    }), /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 12.5
      }
    }, dd ? dd.title : k), /*#__PURE__*/React.createElement("span", {
      style: {
        marginLeft: 'auto',
        fontFamily: HB.mono,
        fontSize: 11,
        color: HB.green
      }
    }, "\u2192 ", ct));
  }), !Object.keys(outbound).length && /*#__PURE__*/React.createElement(Empty, null, "Drives no other domain.")), !ifaceCount && /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: HB.serif,
      fontStyle: 'italic',
      color: HB.inkMute,
      fontSize: 13,
      marginTop: 10
    }
  }, "Self-contained \u2014 no external ports."))));
}

/* ════ BULK — multiple selected ════ */
function BulkPanel(_ref9) {
  var sel = _ref9.sel,
    selNodes = _ref9.selNodes,
    M = _ref9.M,
    DB = _ref9.DB,
    STATUS = _ref9.STATUS,
    bulkStatus = _ref9.bulkStatus,
    bulkDomain = _ref9.bulkDomain,
    bulkAgent = _ref9.bulkAgent,
    onGroup = _ref9.onGroup,
    onDelete = _ref9.onDelete,
    clearSel = _ref9.clearSel,
    domName = _ref9.domName;
  var byDom = {};
  selNodes.forEach(function (n) {
    return byDom[n.dom] = (byDom[n.dom] || 0) + 1;
  });
  return /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: _objectSpread(_objectSpread({}, secStyle), {}, {
      borderBottom: "1px solid ".concat(HB.line),
      display: 'flex',
      alignItems: 'center',
      gap: 10
    })
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: 34,
      height: 34,
      borderRadius: 9,
      display: 'grid',
      placeItems: 'center',
      background: HB.accent,
      color: window.AH && window.AH.onFill || '#180f08',
      flexShrink: 0,
      fontFamily: HB.serif,
      fontSize: 16
    }
  }, sel.size), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: HB.mono,
      fontSize: 8.5,
      color: HB.accent,
      letterSpacing: '0.2em'
    }
  }, "BULK \xB7 MACRO CONTROL"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: HB.serif,
      fontSize: 21,
      letterSpacing: '-0.01em'
    }
  }, sel.size, " nodes selected")), /*#__PURE__*/React.createElement(HIconBtn, {
    name: "x",
    onClick: clearSel
  })), /*#__PURE__*/React.createElement("div", {
    style: secStyle
  }, /*#__PURE__*/React.createElement("div", {
    style: insLabel
  }, "SET STATUS \xB7 ALL"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexWrap: 'wrap',
      gap: 5
    }
  }, STATUS.map(function (s) {
    return /*#__PURE__*/React.createElement("button", {
      key: s,
      onClick: function onClick() {
        return bulkStatus(s);
      },
      style: chip(STC[s])
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        width: 7,
        height: 7,
        borderRadius: 2,
        background: STC[s]
      }
    }), s);
  }))), /*#__PURE__*/React.createElement("div", {
    style: secStyle
  }, /*#__PURE__*/React.createElement("div", {
    style: insLabel
  }, "MOVE TO DOMAIN \xB7 ALL"), /*#__PURE__*/React.createElement("select", {
    onChange: function onChange(e) {
      return e.target.value && bulkDomain(e.target.value);
    },
    value: "",
    style: insInput()
  }, /*#__PURE__*/React.createElement("option", {
    value: ""
  }, "choose domain\u2026"), M.domains.map(function (d) {
    return /*#__PURE__*/React.createElement("option", {
      key: d.key,
      value: d.key
    }, d.title);
  }))), /*#__PURE__*/React.createElement("div", {
    style: secStyle
  }, /*#__PURE__*/React.createElement("div", {
    style: insLabel
  }, "ASSIGN AGENT \xB7 ALL \xB7 WIRED TO FOUNDER BRAIN"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 5
    }
  }, DB.agents.map(function (a) {
    return /*#__PURE__*/React.createElement("button", {
      key: a.id,
      onClick: function onClick() {
        return bulkAgent(a.id);
      },
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 9,
        padding: '8px 10px',
        borderRadius: 8,
        cursor: 'pointer',
        textAlign: 'left',
        border: "1px solid ".concat(HB.line),
        background: HB.paper2,
        color: HB.ink
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        width: 22,
        height: 22,
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
        fontSize: 12.5
      }
    }, a.name));
  }))), /*#__PURE__*/React.createElement("div", {
    style: secStyle
  }, /*#__PURE__*/React.createElement("div", {
    style: insLabel
  }, "SELECTION SPANS"), Object.entries(byDom).map(function (_ref0) {
    var _ref1 = _slicedToArray(_ref0, 2),
      d = _ref1[0],
      n = _ref1[1];
    return /*#__PURE__*/React.createElement("div", {
      key: d,
      style: {
        display: 'flex',
        justifyContent: 'space-between',
        fontFamily: HB.mono,
        fontSize: 11,
        color: HB.inkSoft,
        padding: '3px 0'
      }
    }, /*#__PURE__*/React.createElement("span", null, domName(d)), /*#__PURE__*/React.createElement("span", null, n));
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: 16,
      display: 'flex',
      gap: 8
    }
  }, /*#__PURE__*/React.createElement(HBtn, {
    primary: true,
    onClick: onGroup,
    style: {
      flex: 1,
      justifyContent: 'center'
    }
  }, /*#__PURE__*/React.createElement(CKIcon, {
    name: "grid",
    size: 13
  }), "Group"), /*#__PURE__*/React.createElement(HBtn, {
    danger: true,
    onClick: onDelete,
    style: {
      flex: 1,
      justifyContent: 'center'
    }
  }, /*#__PURE__*/React.createElement(CKIcon, {
    name: "trash",
    size: 13
  }), "Delete all")));
}

/* ════ STEM editor — the node's own parameters, fields, triggers & ports ════ */
/* This is the stem design: the node is grown & controlled by the user. Every
   param is a live widget; any param promotes to a wireable input port; fields &
   triggers are added in place. Mirrors stem-sandbox.jsx NodeBody. */
var ptypeOf = function ptypeOf(p) {
  return p.t || (p.v === true || p.v === false || p.v === 'true' || p.v === 'false' ? 'boolean' : String(p.v).trim() !== '' && !isNaN(parseFloat(p.v)) && isFinite(+p.v) ? 'number' : /^#[0-9a-fA-F]{3,8}$/.test(String(p.v)) ? 'color' : 'string');
};
var PARAM_WIRE = {
  string: 'string',
  number: 'number',
  "boolean": 'boolean',
  color: 'string',
  trigger: 'exec'
};
var ptypeCol = function ptypeCol(t) {
  return window.typeColOf ? window.typeColOf(PARAM_WIRE[t] || 'any') : HB.inkMute;
};
function StemParams(_ref10) {
  var node = _ref10.node,
    patchNode = _ref10.patchNode;
  var params = node.params || [];
  var ports = node.ports || {
    ins: [],
    outs: []
  };
  var promoted = new Set((ports.ins || []).map(function (x) {
    return x.id;
  }));
  var setParam = function setParam(i, patch) {
    patchNode(node.id, {
      params: params.map(function (p, j) {
        return j === i ? _objectSpread(_objectSpread({}, p), patch) : p;
      })
    });
    // A live-graph parameter commits through the governed write; the
    // local patch above keeps the panel instant either way.
    var held = params[i];
    if (patch.v !== undefined && held && held.rel && window.ARCHHUB_SET_PROP) {
      window.ARCHHUB_SET_PROP(held.rel, String(patch.v))["catch"](function () {});
    }
  };
  var delParam = function delParam(i) {
    var p = params[i];
    patchNode(node.id, {
      params: params.filter(function (_, j) {
        return j !== i;
      }),
      ports: _objectSpread(_objectSpread({}, ports), {}, {
        ins: (ports.ins || []).filter(function (x) {
          return x.id !== p.k;
        })
      })
    });
  };
  var addParam = function addParam(t) {
    var n = params.length + 1;
    var base = t === 'trigger' ? {
      k: 'on',
      v: 'on save',
      t: 'trigger'
    } : t === 'boolean' ? {
      k: 'flag' + n,
      v: false,
      t: 'boolean'
    } : t === 'number' ? {
      k: 'value' + n,
      v: 0,
      t: 'number'
    } : t === 'color' ? {
      k: 'color' + n,
      v: '#d97757',
      t: 'color'
    } : {
      k: 'field' + n,
      v: '',
      t: 'string'
    };
    var patch = {
      params: [].concat(_toConsumableArray(params), [base])
    };
    if (t === 'trigger') patch.ports = _objectSpread(_objectSpread({}, ports), {}, {
      ins: [].concat(_toConsumableArray(ports.ins || []), [{
        id: 'exec',
        t: 'exec'
      }])
    });
    patchNode(node.id, patch);
  };
  var promote = function promote(p) {
    var has = promoted.has(p.k);
    var ins = has ? (ports.ins || []).filter(function (x) {
      return x.id !== p.k;
    }) : [].concat(_toConsumableArray(ports.ins || []), [{
      id: p.k,
      t: PARAM_WIRE[ptypeOf(p)] || 'any'
    }]);
    patchNode(node.id, {
      ports: _objectSpread(_objectSpread({}, ports), {}, {
        ins: ins
      })
    });
  };
  var wrap = {
    display: 'flex',
    flexDirection: 'column',
    gap: 7
  };
  var card = function card(on) {
    return {
      border: "1px solid ".concat(on ? HB.accent : HB.line),
      borderRadius: 8,
      padding: '8px 9px',
      background: on ? HB.accentSoft : HB.paper2,
      display: 'flex',
      flexDirection: 'column',
      gap: 7
    };
  };
  var keyInput = {
    flex: 1,
    minWidth: 0,
    border: 'none',
    background: 'transparent',
    color: HB.ink,
    fontFamily: HB.mono,
    fontSize: 11.5,
    outline: 'none',
    padding: 0
  };
  var fieldStyle = {
    flex: 1,
    padding: '5px 8px',
    background: HB.card,
    border: "1px solid ".concat(HB.line),
    borderRadius: 6,
    color: HB.ink,
    fontFamily: HB.mono,
    fontSize: 11.5,
    outline: 'none'
  };
  var tag = function tag(t) {
    return {
      fontFamily: HB.mono,
      fontSize: 8.5,
      color: ptypeCol(t),
      padding: '1px 6px',
      borderRadius: 999,
      border: "1px solid ".concat(ptypeCol(t)),
      flexShrink: 0,
      textTransform: 'lowercase'
    };
  };
  var promoteBtn = function promoteBtn(on) {
    return {
      width: 16,
      height: 16,
      flexShrink: 0,
      borderRadius: on ? 3 : '50%',
      cursor: 'pointer',
      background: on ? HB.accent : 'transparent',
      border: "1.5px solid ".concat(on ? HB.accent : HB.inkMute),
      color: on ? '#fff' : HB.inkMute,
      fontSize: 9,
      lineHeight: 1,
      padding: 0,
      display: 'grid',
      placeItems: 'center'
    };
  };
  var addBtn = {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 3,
    padding: '5px 9px',
    borderRadius: 6,
    cursor: 'pointer',
    fontFamily: HB.mono,
    fontSize: 10,
    border: "1px dashed ".concat(HB.line),
    background: HB.card,
    color: HB.inkSoft
  };
  var widget = function widget(p, i, t) {
    if (t === 'boolean') {
      var on = p.v === true || p.v === 'true';
      return /*#__PURE__*/React.createElement("button", {
        onClick: function onClick() {
          return setParam(i, {
            v: !on
          });
        },
        style: {
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          background: 'none',
          border: 0,
          cursor: 'pointer',
          padding: 0
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
      })), /*#__PURE__*/React.createElement("span", {
        style: {
          fontFamily: HB.mono,
          fontSize: 11,
          color: HB.ink
        }
      }, String(on)));
    }
    if (t === 'number') return /*#__PURE__*/React.createElement("input", {
      type: "number",
      value: p.v,
      onChange: function onChange(e) {
        return setParam(i, {
          v: e.target.value
        });
      },
      style: fieldStyle
    });
    if (t === 'color') return /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 8
      }
    }, /*#__PURE__*/React.createElement("input", {
      type: "color",
      value: /^#[0-9a-fA-F]{6}$/.test(String(p.v)) ? p.v : '#d97757',
      onChange: function onChange(e) {
        return setParam(i, {
          v: e.target.value
        });
      },
      style: {
        width: 22,
        height: 22,
        border: 0,
        background: 'none',
        padding: 0,
        cursor: 'pointer',
        borderRadius: 5
      }
    }), /*#__PURE__*/React.createElement("input", {
      value: p.v,
      onChange: function onChange(e) {
        return setParam(i, {
          v: e.target.value
        });
      },
      style: fieldStyle
    }));
    if (t === 'trigger') return /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 7
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        fontFamily: HB.mono,
        fontSize: 10,
        color: HB.amber
      }
    }, "\u25B7 fires"), /*#__PURE__*/React.createElement("input", {
      value: p.v,
      onChange: function onChange(e) {
        return setParam(i, {
          v: e.target.value
        });
      },
      style: fieldStyle,
      placeholder: "on save \xB7 cron \xB7 webhook\u2026"
    }));
    return /*#__PURE__*/React.createElement("input", {
      value: p.v,
      onChange: function onChange(e) {
        return setParam(i, {
          v: e.target.value
        });
      },
      style: fieldStyle,
      placeholder: "value\u2026"
    });
  };
  return /*#__PURE__*/React.createElement("div", {
    style: wrap
  }, params.length === 0 && /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: HB.serif,
      fontStyle: 'italic',
      fontSize: 12.5,
      color: HB.inkMute
    }
  }, "No parameters yet \u2014 add a field, toggle, or trigger below to grow this node."), params.map(function (p, i) {
    var t = ptypeOf(p);
    var on = promoted.has(p.k);
    return /*#__PURE__*/React.createElement("div", {
      key: i,
      style: card(on)
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 7
      }
    }, /*#__PURE__*/React.createElement("button", {
      onClick: function onClick() {
        return promote(p);
      },
      title: on ? 'demote to dial' : 'promote to wireable input port',
      style: promoteBtn(on)
    }, "\u25C7"), /*#__PURE__*/React.createElement("input", {
      value: p.k,
      onChange: function onChange(e) {
        return setParam(i, {
          k: e.target.value
        });
      },
      style: keyInput
    }), /*#__PURE__*/React.createElement("span", {
      style: tag(t)
    }, t), /*#__PURE__*/React.createElement("button", {
      onClick: function onClick() {
        return delParam(i);
      },
      style: {
        border: 'none',
        background: 'transparent',
        color: HB.inkMute,
        cursor: 'pointer',
        padding: 0,
        display: 'grid',
        placeItems: 'center'
      }
    }, /*#__PURE__*/React.createElement(CKIcon, {
      name: "x",
      size: 12
    }))), widget(p, i, t), on && /*#__PURE__*/React.createElement("div", {
      style: {
        fontFamily: HB.mono,
        fontSize: 9,
        color: HB.accent
      }
    }, "\u25B6 exposed as input port \xB7 wireable on the map"));
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexWrap: 'wrap',
      gap: 6,
      marginTop: 2
    }
  }, [['field', '＋ Field'], ['number', '＋ Number'], ['boolean', '＋ Toggle'], ['color', '＋ Color'], ['trigger', '＋ Trigger']].map(function (_ref11) {
    var _ref12 = _slicedToArray(_ref11, 2),
      t = _ref12[0],
      l = _ref12[1];
    return /*#__PURE__*/React.createElement("button", {
      key: t,
      onClick: function onClick() {
        return addParam(t);
      },
      style: addBtn
    }, l);
  })), (ports.ins || []).length > 0 && /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: HB.mono,
      fontSize: 9.5,
      color: HB.inkMute,
      paddingTop: 2
    }
  }, /*#__PURE__*/React.createElement("b", {
    style: {
      color: HB.accent
    }
  }, ports.ins.length), " port", ports.ins.length > 1 ? 's' : '', " promoted \u2014 now wireable knobs on the node"));
}

/* ════ MICRO — single node inspector ════ */
function NodeInspector(_ref13) {
  var M = _ref13.M,
    node = _ref13.node,
    DB = _ref13.DB,
    assign = _ref13.assign,
    STATUS = _ref13.STATUS,
    CATS = _ref13.CATS,
    patchNode = _ref13.patchNode,
    delNode = _ref13.delNode,
    toggleAgent = _ref13.toggleAgent,
    onClose = _ref13.onClose,
    openRoom = _ref13.openRoom,
    focusNode = _ref13.focusNode,
    domName = _ref13.domName,
    _onRun = _ref13.onRun,
    _onVariant = _ref13.onVariant,
    onWatch = _ref13.onWatch;
  var _React$useState3 = React.useState('control'),
    _React$useState4 = _slicedToArray(_React$useState3, 2),
    tab = _React$useState4[0],
    setTab = _React$useState4[1];
  var RT = window.RT;
  var outs = M.wires.filter(function (w) {
    return w.a === node.id;
  });
  var ins = M.wires.filter(function (w) {
    return w.b === node.id;
  });
  var sigSelf = window.sigOf ? window.sigOf(node) : 'value';
  var dom = M.domains.find(function (d) {
    return d.key === node.dom;
  });
  var myAgents = assign[node.id] || [];
  var pipe = window.nodePipeline ? window.nodePipeline(node) : node.pipeline || [];
  var setPipe = function setPipe(p) {
    return patchNode(node.id, {
      pipeline: p
    });
  };
  var setStage = function setStage(i, k, v) {
    return setPipe(pipe.map(function (s, j) {
      return j === i ? _objectSpread(_objectSpread({}, s), {}, _defineProperty({}, k, v)) : s;
    }));
  };
  var addStage = function addStage() {
    return setPipe([].concat(_toConsumableArray(pipe), [{
      id: node.id + '_s' + Date.now().toString(36),
      t: 'new stage',
      role: 'process',
      status: 'vision'
    }]));
  };
  var delStage = function delStage(i) {
    return setPipe(pipe.filter(function (_, j) {
      return j !== i;
    }));
  };
  return /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'sticky',
      top: 0,
      zIndex: 2,
      background: HB.card,
      borderBottom: "1px solid ".concat(HB.line),
      padding: '14px 16px'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'flex-start',
      gap: 10
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: 30,
      height: 30,
      borderRadius: 7,
      display: 'grid',
      placeItems: 'center',
      background: catCol(node.cat) + '1e',
      color: catCol(node.cat),
      flexShrink: 0,
      marginTop: 2
    }
  }, /*#__PURE__*/React.createElement(CKIcon, {
    name: "bolt",
    size: 15
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      minWidth: 0
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: HB.mono,
      fontSize: 8.5,
      color: dom ? dom.col : HB.accent,
      letterSpacing: '0.14em'
    }
  }, (node.cat || '').toUpperCase(), " \xB7 ", dom ? dom.title : node.dom), /*#__PURE__*/React.createElement("input", {
    value: node.title,
    onChange: function onChange(e) {
      return patchNode(node.id, {
        title: e.target.value
      });
    },
    style: {
      width: '100%',
      border: 'none',
      background: 'transparent',
      fontFamily: HB.serif,
      fontSize: 21,
      letterSpacing: '-0.01em',
      color: HB.ink,
      outline: 'none',
      padding: 0,
      marginTop: 2
    }
  })), /*#__PURE__*/React.createElement(HIconBtn, {
    name: "x",
    onClick: onClose
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 8,
      marginTop: 11
    }
  }, /*#__PURE__*/React.createElement("button", {
    onClick: function onClick() {
      return _onRun && _onRun(node.id);
    },
    disabled: RT && RT.rtState(node) === 'running',
    style: {
      display: 'inline-flex',
      alignItems: 'center',
      gap: 7,
      padding: '8px 16px',
      borderRadius: 8,
      border: 'none',
      background: HB.accent,
      color: window.AH && window.AH.onFill || '#180f08',
      cursor: 'pointer',
      fontFamily: HB.mono,
      fontSize: 12,
      fontWeight: 700
    }
  }, RT && RT.rtState(node) === 'running' ? '◴ running…' : '▸ Run'), RT && /*#__PURE__*/React.createElement(RT.RTChip, {
    state: RT.rtState(node)
  }), /*#__PURE__*/React.createElement("button", {
    onClick: function onClick() {
      return onWatch && onWatch(node.id);
    },
    title: "Drop a watcher node wired to this \u2014 shows its live result on the map",
    style: {
      marginLeft: 'auto',
      display: 'inline-flex',
      alignItems: 'center',
      gap: 5,
      padding: '7px 11px',
      borderRadius: 8,
      border: "1px solid ".concat(HB.line),
      background: HB.paper2,
      color: HB.inkSoft,
      cursor: 'pointer',
      fontFamily: HB.mono,
      fontSize: 10.5
    }
  }, "\u25C9 Watch")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 4,
      marginTop: 11
    }
  }, [['control', 'Control'], ['pipeline', "Pipeline ".concat(pipe.length)], ['runs', "Runs ".concat(RT ? RT.rtRuns(node).length : 0)], ['wires', "Ports ".concat(outs.length + ins.length)]].map(function (_ref14) {
    var _ref15 = _slicedToArray(_ref14, 2),
      k = _ref15[0],
      l = _ref15[1];
    return /*#__PURE__*/React.createElement("button", {
      key: k,
      onClick: function onClick() {
        return setTab(k);
      },
      style: {
        flex: 1,
        padding: '6px 0',
        borderRadius: 7,
        cursor: 'pointer',
        fontFamily: HB.mono,
        fontSize: 9.5,
        border: "1px solid ".concat(tab === k ? HB.accent : HB.line),
        background: tab === k ? HB.accentSoft : 'transparent',
        color: tab === k ? HB.accentHi : HB.inkSoft
      }
    }, l);
  }))), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: 16
    }
  }, tab === 'control' && /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 14
    }
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: insLabel
  }, "INTENT"), /*#__PURE__*/React.createElement("textarea", {
    value: node.sub,
    onChange: function onChange(e) {
      return patchNode(node.id, {
        sub: e.target.value
      });
    },
    rows: 2,
    style: insInput()
  })), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: _objectSpread(_objectSpread({}, insLabel), {}, {
      display: 'flex',
      alignItems: 'center',
      gap: 6
    })
  }, "PARAMETERS \xB7 FIELDS \xB7 TRIGGERS", /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: HB.mono,
      fontSize: 8,
      color: HB.accent,
      letterSpacing: '0.04em',
      textTransform: 'none'
    }
  }, "\u2014 the stem: grow & wire this node")), /*#__PURE__*/React.createElement(StemParams, {
    node: node,
    patchNode: patchNode
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'grid',
      gridTemplateColumns: '1fr 1fr',
      gap: 10
    }
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: insLabel
  }, "DOMAIN"), /*#__PURE__*/React.createElement("select", {
    value: node.dom,
    onChange: function onChange(e) {
      return patchNode(node.id, {
        dom: e.target.value
      });
    },
    style: insInput()
  }, M.domains.map(function (d) {
    return /*#__PURE__*/React.createElement("option", {
      key: d.key,
      value: d.key
    }, d.title);
  }))), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: insLabel
  }, "CATEGORY"), /*#__PURE__*/React.createElement("select", {
    value: node.cat,
    onChange: function onChange(e) {
      return patchNode(node.id, {
        cat: e.target.value
      });
    },
    style: insInput()
  }, CATS.map(function (c) {
    return /*#__PURE__*/React.createElement("option", {
      key: c
    }, c);
  })))), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: insLabel
  }, "STATUS \xB7 THE LIVE ROADMAP"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexWrap: 'wrap',
      gap: 5
    }
  }, STATUS.map(function (s) {
    return /*#__PURE__*/React.createElement("button", {
      key: s,
      onClick: function onClick() {
        return patchNode(node.id, {
          status: s
        });
      },
      style: {
        display: 'inline-flex',
        alignItems: 'center',
        gap: 5,
        padding: '5px 10px',
        borderRadius: 999,
        cursor: 'pointer',
        fontFamily: HB.mono,
        fontSize: 10.5,
        textTransform: 'capitalize',
        border: "1px solid ".concat(node.status === s ? STC[s] : HB.line),
        background: node.status === s ? STC[s] + '20' : 'transparent',
        color: node.status === s ? STC[s] : HB.inkSoft
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        width: 7,
        height: 7,
        borderRadius: 2,
        background: STC[s]
      }
    }), s);
  }))), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: insLabel
  }, "OWNED BY AGENTS \xB7 WIRED TO FOUNDER BRAIN"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 6
    }
  }, DB.agents.map(function (a) {
    var on = myAgents.includes(a.id);
    return /*#__PURE__*/React.createElement("button", {
      key: a.id,
      onClick: function onClick() {
        return toggleAgent(node.id, a.id);
      },
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 9,
        padding: '8px 10px',
        borderRadius: 8,
        cursor: 'pointer',
        textAlign: 'left',
        border: "1px solid ".concat(on ? HB.accent : HB.line),
        background: on ? HB.accentSoft : HB.paper2
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        position: 'relative',
        flexShrink: 0,
        display: 'grid',
        placeItems: 'center'
      }
    }, /*#__PURE__*/React.createElement(HAvatar, {
      name: a.name,
      size: 26
    }), on && /*#__PURE__*/React.createElement("span", {
      style: {
        position: 'absolute',
        inset: -2,
        borderRadius: '50%',
        border: "2px solid ".concat(HB.accent)
      }
    })), /*#__PURE__*/React.createElement("span", {
      style: {
        flex: 1,
        minWidth: 0
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 12.5,
        fontWeight: 500,
        display: 'block'
      }
    }, a.name), /*#__PURE__*/React.createElement("span", {
      style: {
        fontFamily: HB.mono,
        fontSize: 9.5,
        color: HB.inkMute
      }
    }, (DB.models.find(function (m) {
      return m.id === a.model;
    }) || {}).name)), on ? /*#__PURE__*/React.createElement("span", {
      style: {
        color: HB.accent
      }
    }, /*#__PURE__*/React.createElement(CKIcon, {
      name: "check",
      size: 15
    })) : /*#__PURE__*/React.createElement("span", {
      style: {
        fontFamily: HB.mono,
        fontSize: 9,
        color: HB.inkMute,
        letterSpacing: '0.1em'
      }
    }, "ASSIGN"));
  }))), /*#__PURE__*/React.createElement(HBtn, {
    danger: true,
    small: true,
    onClick: function onClick() {
      return delNode(node.id);
    },
    style: {
      alignSelf: 'flex-start'
    }
  }, /*#__PURE__*/React.createElement(CKIcon, {
    name: "trash",
    size: 12
  }), "Delete node")), tab === 'pipeline' && /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 8
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: insLabel
  }, "INTERNAL PIPELINE \xB7 THIS NODE IS A MICRO-DOMAIN"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: HB.mono,
      fontSize: 9.5,
      color: HB.inkMute,
      marginBottom: 2
    }
  }, "double-click the node on the map to expand its pipeline in place"), pipe.map(function (s, i) {
    var col = {
      "in": HB.blue,
      process: HB.purple,
      out: HB.green
    }[s.role] || HB.purple;
    return /*#__PURE__*/React.createElement("div", {
      key: s.id || i,
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 7,
        border: "1px solid ".concat(HB.line),
        borderRadius: 8,
        padding: '7px 9px',
        background: HB.paper2
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        width: 8,
        height: 8,
        borderRadius: 2,
        background: STC[s.status] || col,
        flexShrink: 0
      }
    }), /*#__PURE__*/React.createElement("input", {
      value: s.t,
      onChange: function onChange(e) {
        return setStage(i, 't', e.target.value);
      },
      style: {
        flex: 1,
        border: 'none',
        background: 'transparent',
        color: HB.ink,
        fontSize: 12,
        outline: 'none',
        fontFamily: HB.sans
      }
    }), /*#__PURE__*/React.createElement("select", {
      value: s.role,
      onChange: function onChange(e) {
        return setStage(i, 'role', e.target.value);
      },
      style: {
        border: "1px solid ".concat(HB.line),
        background: HB.card,
        color: col,
        borderRadius: 5,
        fontFamily: HB.mono,
        fontSize: 9.5,
        padding: '2px 4px'
      }
    }, ['in', 'process', 'out'].map(function (r) {
      return /*#__PURE__*/React.createElement("option", {
        key: r
      }, r);
    })), /*#__PURE__*/React.createElement("button", {
      onClick: function onClick() {
        return delStage(i);
      },
      style: {
        border: 'none',
        background: 'transparent',
        color: HB.inkMute,
        cursor: 'pointer'
      }
    }, /*#__PURE__*/React.createElement(CKIcon, {
      name: "x",
      size: 12
    })));
  }), /*#__PURE__*/React.createElement(HBtn, {
    small: true,
    onClick: addStage,
    style: {
      alignSelf: 'flex-start',
      marginTop: 4
    }
  }, /*#__PURE__*/React.createElement(CKIcon, {
    name: "plus",
    size: 12
  }), "Add stage")), tab === 'runs' && RT && /*#__PURE__*/React.createElement(RT.RunsBody, {
    node: node,
    onRun: function onRun() {
      return _onRun && _onRun(node.id);
    },
    onVariant: function onVariant(r) {
      return _onVariant && _onVariant(node.id, r);
    }
  }), tab === 'wires' && /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 16
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 8,
      padding: '9px 11px',
      borderRadius: 8,
      background: HB.paper2,
      border: "1px solid ".concat(HB.lineSoft)
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: HB.mono,
      fontSize: 9,
      color: HB.inkMute,
      letterSpacing: '0.1em'
    }
  }, "EMITS"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: HB.mono,
      fontSize: 10.5,
      color: catCol(node.cat),
      padding: '2px 8px',
      borderRadius: 999,
      border: "1px solid ".concat(catCol(node.cat)),
      textTransform: 'lowercase'
    }
  }, sigSelf), /*#__PURE__*/React.createElement("span", {
    style: {
      marginLeft: 'auto',
      fontFamily: HB.mono,
      fontSize: 9.5,
      color: HB.inkMute
    }
  }, ins.length, " in \xB7 ", outs.length, " out")), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: _objectSpread(_objectSpread({}, insLabel), {}, {
      color: HB.green
    })
  }, "OUT PORTS \u2192 (", outs.length, ")"), outs.length === 0 && /*#__PURE__*/React.createElement(Empty, null, "Drives nothing yet."), outs.map(function (w, i) {
    var t = M.nodes.find(function (n) {
      return n.id === w.b;
    });
    return /*#__PURE__*/React.createElement(WireRow, {
      key: i,
      dir: "\u2192",
      node: t,
      why: w.why,
      sig: sigSelf,
      sigCol: catCol(node.cat),
      onClick: function onClick() {
        return t && focusNode(t.id);
      }
    });
  })), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: _objectSpread(_objectSpread({}, insLabel), {}, {
      color: HB.blue
    })
  }, "IN PORTS \u2190 (", ins.length, ")"), ins.length === 0 && /*#__PURE__*/React.createElement(Empty, null, "Nothing feeds it."), ins.map(function (w, i) {
    var s = M.nodes.find(function (n) {
      return n.id === w.a;
    });
    var sg = window.sigOf ? window.sigOf(s) : 'value';
    return /*#__PURE__*/React.createElement(WireRow, {
      key: i,
      dir: "\u2190",
      node: s,
      why: w.why,
      sig: sg,
      sigCol: s ? catCol(s.cat) : HB.inkMute,
      onClick: function onClick() {
        return s && focusNode(s.id);
      }
    });
  }))), tab === 'evidence' && /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 14
    }
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: insLabel
  }, "EVIDENCE \xB7 THE FEDERATION LINK"), /*#__PURE__*/React.createElement("input", {
    value: node.evidence_ref || '',
    onChange: function onChange(e) {
      return patchNode(node.id, {
        evidence_ref: e.target.value
      });
    },
    placeholder: "file:path \xB7 test:id \xB7 brain:\u2026",
    style: insInput(true)
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'grid',
      gridTemplateColumns: '1fr 1fr',
      gap: 10
    }
  }, /*#__PURE__*/React.createElement(Stat, {
    label: "AUTHORITY",
    value: node.authority_source || 'vision'
  }), /*#__PURE__*/React.createElement(Stat, {
    label: "VERIFIED",
    value: node.last_verified || 'never'
  }), /*#__PURE__*/React.createElement(Stat, {
    label: "BIM PHASE",
    value: node.bim_phase || '—'
  }), /*#__PURE__*/React.createElement(Stat, {
    label: "STANDARD",
    value: node.standard || '—'
  })), (node.params || []).length > 0 && /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: insLabel
  }, "PARAMETERS"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 5
    }
  }, node.params.map(function (p, i) {
    return /*#__PURE__*/React.createElement("div", {
      key: i,
      style: {
        display: 'flex',
        gap: 8,
        fontFamily: HB.mono,
        fontSize: 11,
        padding: '6px 9px',
        borderRadius: 6,
        background: HB.paper2,
        border: "1px solid ".concat(HB.lineSoft)
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        color: HB.inkMute
      }
    }, p.k), /*#__PURE__*/React.createElement("span", {
      style: {
        marginLeft: 'auto',
        color: HB.ink
      }
    }, p.v));
  }))))));
}
var WireRow = function WireRow(_ref16) {
  var dir = _ref16.dir,
    node = _ref16.node,
    why = _ref16.why,
    sig = _ref16.sig,
    sigCol = _ref16.sigCol,
    onClick = _ref16.onClick;
  return /*#__PURE__*/React.createElement("div", {
    className: "hb-rowh",
    onClick: onClick,
    style: {
      display: 'flex',
      alignItems: 'flex-start',
      gap: 8,
      padding: '8px 9px',
      borderRadius: 7,
      cursor: 'pointer',
      marginBottom: 2
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      color: dir === '→' ? HB.green : HB.blue,
      fontFamily: HB.mono,
      fontSize: 13,
      marginTop: 1
    }
  }, dir), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      minWidth: 0
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 6
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 12.5,
      fontWeight: 500
    }
  }, node ? node.title : '—'), sig && /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: HB.mono,
      fontSize: 8.5,
      color: sigCol || HB.inkMute,
      padding: '1px 6px',
      borderRadius: 999,
      border: "1px solid ".concat(sigCol || HB.line),
      flexShrink: 0
    }
  }, sig)), why && /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: HB.mono,
      fontSize: 9.5,
      color: HB.inkMute,
      marginTop: 2,
      lineHeight: 1.4
    }
  }, why)), node && /*#__PURE__*/React.createElement(HPill, {
    k: node.status
  }, node.status));
};
var Stat = function Stat(_ref17) {
  var label = _ref17.label,
    value = _ref17.value;
  return /*#__PURE__*/React.createElement("div", {
    style: {
      padding: '8px 10px',
      borderRadius: 7,
      background: HB.paper2,
      border: "1px solid ".concat(HB.lineSoft)
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: HB.mono,
      fontSize: 8,
      color: HB.inkMute,
      letterSpacing: '0.12em'
    }
  }, label), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: HB.mono,
      fontSize: 11.5,
      color: HB.ink,
      marginTop: 3,
      wordBreak: 'break-word'
    }
  }, value));
};
var Empty = function Empty(_ref18) {
  var children = _ref18.children;
  return /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: HB.serif,
      fontStyle: 'italic',
      fontSize: 13,
      color: HB.inkMute
    }
  }, children);
};
var chip = function chip(col) {
  return {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 5,
    padding: '5px 10px',
    borderRadius: 999,
    cursor: 'pointer',
    fontFamily: HB.mono,
    fontSize: 10.5,
    textTransform: 'capitalize',
    border: "1px solid ".concat(HB.line),
    background: 'transparent',
    color: HB.inkSoft
  };
};
var miniAct = function miniAct(col, fill) {
  return {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 4,
    padding: '5px 9px',
    borderRadius: 6,
    cursor: 'pointer',
    fontFamily: HB.mono,
    fontSize: 10,
    border: "1px solid ".concat(col),
    background: fill ? col : 'transparent',
    color: fill ? '#fff' : HB.inkSoft
  };
};

/* ════ name modal (group / domain) ════ */
function NameModal(_ref19) {
  var title = _ref19.title,
    placeholder = _ref19.placeholder,
    colors = _ref19.colors,
    onSave = _ref19.onSave,
    onClose = _ref19.onClose;
  var _React$useState5 = React.useState(''),
    _React$useState6 = _slicedToArray(_React$useState5, 2),
    name = _React$useState6[0],
    setName = _React$useState6[1];
  var _React$useState7 = React.useState(colors ? colors[0] : null),
    _React$useState8 = _slicedToArray(_React$useState7, 2),
    col = _React$useState8[0],
    setCol = _React$useState8[1];
  var ref = React.useRef(null);
  React.useEffect(function () {
    ref.current && ref.current.focus();
  }, []);
  return /*#__PURE__*/React.createElement("div", {
    onClick: onClose,
    style: {
      position: 'fixed',
      inset: 0,
      zIndex: 90,
      background: 'rgba(0,0,0,0.32)',
      display: 'grid',
      placeItems: 'center',
      animation: 'hbFade .14s'
    }
  }, /*#__PURE__*/React.createElement("div", {
    onClick: function onClick(e) {
      return e.stopPropagation();
    },
    style: {
      width: 400,
      background: HB.card,
      border: "1px solid ".concat(HB.line),
      borderRadius: 14,
      padding: 20,
      boxShadow: '0 30px 80px rgba(0,0,0,.3)'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: HB.serif,
      fontSize: 22,
      letterSpacing: '-0.01em',
      marginBottom: 14
    }
  }, title), /*#__PURE__*/React.createElement("input", {
    ref: ref,
    value: name,
    onChange: function onChange(e) {
      return setName(e.target.value);
    },
    onKeyDown: function onKeyDown(e) {
      return e.key === 'Enter' && name.trim() && onSave(name.trim(), col);
    },
    placeholder: placeholder,
    style: _objectSpread(_objectSpread({}, insInput()), {}, {
      fontSize: 14,
      padding: '10px 12px'
    })
  }), colors && /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 7,
      marginTop: 12
    }
  }, colors.map(function (c) {
    return /*#__PURE__*/React.createElement("button", {
      key: c,
      onClick: function onClick() {
        return setCol(c);
      },
      style: {
        width: 26,
        height: 26,
        borderRadius: 7,
        background: c,
        border: col === c ? "2px solid ".concat(HB.ink) : '2px solid transparent',
        cursor: 'pointer'
      }
    });
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      justifyContent: 'flex-end',
      gap: 8,
      marginTop: 18
    }
  }, /*#__PURE__*/React.createElement(HBtn, {
    ghost: true,
    onClick: onClose
  }, "Cancel"), /*#__PURE__*/React.createElement(HBtn, {
    primary: true,
    onClick: function onClick() {
      return name.trim() && onSave(name.trim(), col);
    }
  }, /*#__PURE__*/React.createElement(CKIcon, {
    name: "check",
    size: 13
  }), "Create"))));
}

/* ════ FIELD — a super grand node: a group of domains ════ */
function FieldPanel(_ref20) {
  var M = _ref20.M,
    fieldId = _ref20.fieldId,
    patchField = _ref20.patchField,
    onUngroup = _ref20.onUngroup,
    onEnterDomain = _ref20.onEnterDomain,
    onClose = _ref20.onClose;
  var f = (M.fields || []).find(function (x) {
    return x.id === fieldId;
  }) || {};
  var doms = M.domains.filter(function (d) {
    return (f.domKeys || []).includes(d.key);
  });
  var nodeCount = M.nodes.filter(function (n) {
    return (f.domKeys || []).includes(n.dom);
  }).length;
  return /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'sticky',
      top: 0,
      zIndex: 2,
      background: HB.card,
      borderBottom: "1px solid ".concat(HB.line),
      padding: '14px 16px'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'flex-start',
      gap: 10
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: 32,
      height: 32,
      borderRadius: 8,
      display: 'grid',
      placeItems: 'center',
      background: (f.col || HB.blue) + '22',
      color: f.col || HB.blue,
      flexShrink: 0,
      marginTop: 2,
      fontSize: 16
    }
  }, "\u2B21"), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      minWidth: 0
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: HB.mono,
      fontSize: 8.5,
      color: f.col || HB.blue,
      letterSpacing: '0.16em'
    }
  }, "FIELD \xB7 SUPER GRAND NODE \xB7 ", doms.length, " DOMAINS"), /*#__PURE__*/React.createElement("input", {
    value: f.title || '',
    onChange: function onChange(e) {
      return patchField(fieldId, {
        title: e.target.value
      });
    },
    style: {
      width: '100%',
      border: 'none',
      background: 'transparent',
      fontFamily: HB.serif,
      fontSize: 23,
      letterSpacing: '-0.02em',
      color: HB.ink,
      outline: 'none',
      padding: 0,
      marginTop: 2
    }
  })), /*#__PURE__*/React.createElement(HIconBtn, {
    name: "x",
    onClick: onClose
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: HB.mono,
      fontSize: 9.5,
      color: HB.inkMute,
      marginTop: 8
    }
  }, doms.length, " grand nodes \xB7 ", nodeCount, " capabilities inside")), /*#__PURE__*/React.createElement("div", {
    style: secStyle
  }, /*#__PURE__*/React.createElement("div", {
    style: insLabel
  }, "MEMBER DOMAINS"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 5
    }
  }, doms.map(function (d) {
    return /*#__PURE__*/React.createElement("button", {
      key: d.key,
      onClick: function onClick() {
        return onEnterDomain(d.key);
      },
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 9,
        padding: '8px 10px',
        borderRadius: 8,
        cursor: 'pointer',
        textAlign: 'left',
        border: "1px solid ".concat(HB.line),
        background: HB.paper2,
        color: HB.ink
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        width: 9,
        height: 9,
        borderRadius: 3,
        background: d.col,
        flexShrink: 0
      }
    }), /*#__PURE__*/React.createElement("span", {
      style: {
        flex: 1,
        fontSize: 12.5
      }
    }, d.title), /*#__PURE__*/React.createElement("span", {
      style: {
        fontFamily: HB.mono,
        fontSize: 10,
        color: HB.inkMute
      }
    }, M.nodes.filter(function (n) {
      return n.dom === d.key;
    }).length));
  }))), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: 16
    }
  }, /*#__PURE__*/React.createElement(HBtn, {
    onClick: function onClick() {
      return onUngroup(fieldId);
    },
    style: {
      width: '100%',
      justifyContent: 'center'
    }
  }, /*#__PURE__*/React.createElement(CKIcon, {
    name: "grid",
    size: 13
  }), "Ungroup field \u2014 keep domains")));
}

/* ════ MULTI — a mixed selection of domains (and loose nodes), ready to group up ════ */
function MultiPanel(_ref21) {
  var selDomains = _ref21.selDomains,
    selNodes = _ref21.selNodes,
    M = _ref21.M,
    onGroupField = _ref21.onGroupField,
    clearSel = _ref21.clearSel;
  var doms = M.domains.filter(function (d) {
    return selDomains.includes(d.key);
  });
  var total = selDomains.length + selNodes.size;
  return /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: _objectSpread(_objectSpread({}, secStyle), {}, {
      borderBottom: "1px solid ".concat(HB.line),
      display: 'flex',
      alignItems: 'center',
      gap: 10
    })
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: 34,
      height: 34,
      borderRadius: 9,
      display: 'grid',
      placeItems: 'center',
      background: HB.blue,
      color: '#fff',
      flexShrink: 0,
      fontFamily: HB.serif,
      fontSize: 16
    }
  }, total), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: HB.mono,
      fontSize: 8.5,
      color: HB.blue,
      letterSpacing: '0.2em'
    }
  }, "MIXED SELECTION"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: HB.serif,
      fontSize: 21,
      letterSpacing: '-0.01em'
    }
  }, selDomains.length, " domain", selDomains.length !== 1 ? 's' : '', selNodes.size ? " + ".concat(selNodes.size, " node").concat(selNodes.size !== 1 ? 's' : '') : '')), /*#__PURE__*/React.createElement(HIconBtn, {
    name: "x",
    onClick: clearSel
  })), /*#__PURE__*/React.createElement("div", {
    style: secStyle
  }, /*#__PURE__*/React.createElement("div", {
    style: insLabel
  }, "SELECTED DOMAINS"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 4
    }
  }, doms.map(function (d) {
    return /*#__PURE__*/React.createElement("div", {
      key: d.key,
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        fontFamily: HB.mono,
        fontSize: 11.5,
        color: HB.inkSoft,
        padding: '3px 0'
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        width: 8,
        height: 8,
        borderRadius: 2,
        background: d.col
      }
    }), d.title);
  }), selNodes.size > 0 && /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: HB.mono,
      fontSize: 10.5,
      color: HB.inkMute,
      marginTop: 4
    }
  }, "+ ", selNodes.size, " loose node", selNodes.size !== 1 ? 's' : '', " \u2192 wrapped into a grand node"))), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: 16
    }
  }, /*#__PURE__*/React.createElement(HBtn, {
    primary: true,
    onClick: onGroupField,
    style: {
      width: '100%',
      justifyContent: 'center'
    }
  }, /*#__PURE__*/React.createElement(CKIcon, {
    name: "grid",
    size: 13
  }), "Group"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: HB.mono,
      fontSize: 9.5,
      color: HB.inkMute,
      marginTop: 9,
      textAlign: 'center',
      lineHeight: 1.5
    }
  }, "Grouping makes one node out of what you picked. The same node primitive, one tier up.")));
}

// MULTI-FIELD — 2+ fields selected. This is the rung that makes grouping unbounded: fields
// group into a bigger field, and that field can be grouped again, with no cap.
function MultiFieldPanel(_ref22) {
  var M = _ref22.M,
    ids = _ref22.ids,
    onGroup = _ref22.onGroup,
    clearSel = _ref22.clearSel;
  var all = M.fields || [];
  var byId = {};
  all.forEach(function (f) {
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
  var picked = ids.map(function (id) {
    return byId[id];
  }).filter(Boolean);
  var nextTier = 1 + Math.max.apply(Math, _toConsumableArray(picked.map(function (f) {
    return _depthOf(f.id);
  })));
  var SUP = ['', '', '²', '³', '⁴', '⁵', '⁶', '⁷', '⁸', '⁹'];
  var sup = nextTier > 1 ? SUP[nextTier] != null ? SUP[nextTier] : '^' + nextTier : '';
  return /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: secStyle
  }, /*#__PURE__*/React.createElement("div", {
    style: insLabel
  }, "MULTI SELECTION"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: HB.serif,
      fontSize: 21,
      color: HB.ink,
      marginTop: 4
    }
  }, picked.length, " fields"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: HB.mono,
      fontSize: 10.5,
      color: HB.inkSoft,
      marginTop: 6,
      lineHeight: 1.6
    }
  }, "Group these into one field a tier up. Depth is unbounded \u2014 the result can be grouped again.")), /*#__PURE__*/React.createElement("div", {
    style: secStyle
  }, /*#__PURE__*/React.createElement("div", {
    style: insLabel
  }, "MEMBERS"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 5,
      marginTop: 8
    }
  }, picked.map(function (f) {
    return /*#__PURE__*/React.createElement("div", {
      key: f.id,
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        padding: '6px 9px',
        borderRadius: 6,
        background: HB.paper2
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        width: 8,
        height: 8,
        borderRadius: 2,
        background: f.col || HB.blue,
        flexShrink: 0
      }
    }), /*#__PURE__*/React.createElement("span", {
      style: {
        flex: 1,
        fontFamily: HB.sans,
        fontSize: 12,
        color: HB.ink
      }
    }, f.title), /*#__PURE__*/React.createElement("span", {
      style: {
        fontFamily: HB.mono,
        fontSize: 9.5,
        color: HB.inkMute
      }
    }, "tier ", _depthOf(f.id), " \xB7 ", (f.domKeys || []).length + (f.fieldIds || []).length));
  }))), /*#__PURE__*/React.createElement("div", {
    style: secStyle
  }, /*#__PURE__*/React.createElement(HBtn, {
    primary: true,
    onClick: onGroup,
    style: {
      width: '100%',
      justifyContent: 'center'
    }
  }, "\u229E Group", sup), /*#__PURE__*/React.createElement(HBtn, {
    onClick: clearSel,
    style: {
      width: '100%',
      justifyContent: 'center',
      marginTop: 8
    }
  }, "Clear")));
}
function WirePanel(_ref23) {
  var M = _ref23.M,
    w = _ref23.w,
    onDelete = _ref23.onDelete,
    onGoto = _ref23.onGoto,
    onClose = _ref23.onClose;
  var nodeById = {};
  M.nodes.forEach(function (n) {
    return nodeById[n.id] = n;
  });
  var domById = {};
  M.domains.forEach(function (d) {
    return domById[d.key] = d;
  });
  var domOfN = {};
  M.nodes.forEach(function (n) {
    return domOfN[n.id] = n.dom;
  });
  // every real wire this visible line stands for
  var members = M.wires.filter(function (x) {
    var da = domOfN[x.a] || x.a,
      db = domOfN[x.b] || x.b;
    return w.cross ? da === w.da && db === w.db || da === w.db && db === w.da : x.a === w.a && x.b === w.b || x.a === w.b && x.b === w.a;
  });
  var A = domById[w.da],
    B = domById[w.db];
  var sig = function sig(id) {
    var n = nodeById[id];
    return n ? window.sigOf ? window.sigOf(n) : n.cat : '—';
  };
  return /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: secStyle
  }, /*#__PURE__*/React.createElement("div", {
    style: insLabel
  }, w.cross ? 'CROSS-DOMAIN WIRE' : 'WIRE'), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: HB.serif,
      fontSize: 20,
      lineHeight: 1.15,
      marginTop: 4
    }
  }, A ? A.title : w.da, " ", /*#__PURE__*/React.createElement("span", {
    style: {
      color: HB.accent
    }
  }, "\u2192"), " ", B ? B.title : w.db), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: HB.mono,
      fontSize: 11,
      color: HB.inkSoft,
      marginTop: 6
    }
  }, members.length, " underlying wire", members.length === 1 ? '' : 's', w.cross ? ' · rolled up into one line' : '')), /*#__PURE__*/React.createElement("div", {
    style: secStyle
  }, /*#__PURE__*/React.createElement("div", {
    style: insLabel
  }, "WHAT IS WIRED TO WHAT"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 1,
      marginTop: 8
    }
  }, members.slice(0, 24).map(function (x, i) {
    var a = nodeById[x.a],
      bb = nodeById[x.b];
    return /*#__PURE__*/React.createElement("div", {
      key: i,
      style: {
        padding: '7px 8px',
        borderRadius: 5,
        background: i % 2 ? 'transparent' : HB.paper2
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 6,
        fontFamily: HB.sans,
        fontSize: 12
      }
    }, /*#__PURE__*/React.createElement("button", {
      onClick: function onClick() {
        return a && onGoto(a.id);
      },
      style: {
        border: 0,
        background: 'transparent',
        padding: 0,
        color: HB.ink,
        cursor: a ? 'pointer' : 'default',
        fontSize: 12,
        textAlign: 'left'
      }
    }, a ? a.title : x.a), /*#__PURE__*/React.createElement("span", {
      style: {
        color: HB.accent,
        flexShrink: 0
      }
    }, "\u2192"), /*#__PURE__*/React.createElement("button", {
      onClick: function onClick() {
        return bb && onGoto(bb.id);
      },
      style: {
        border: 0,
        background: 'transparent',
        padding: 0,
        color: HB.ink,
        cursor: bb ? 'pointer' : 'default',
        fontSize: 12,
        textAlign: 'left'
      }
    }, bb ? bb.title : x.b)), /*#__PURE__*/React.createElement("div", {
      style: {
        fontFamily: HB.mono,
        fontSize: 9,
        color: HB.inkMute,
        marginTop: 2
      }
    }, sig(x.a), " \u2192 ", sig(x.b), x.why ? ' · ' + x.why : ''));
  }), members.length > 24 && /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: HB.mono,
      fontSize: 10,
      color: HB.inkDim,
      padding: '6px 8px'
    }
  }, "+", members.length - 24, " more"))), /*#__PURE__*/React.createElement("div", {
    style: _objectSpread(_objectSpread({}, secStyle), {}, {
      borderBottom: 'none',
      display: 'flex',
      gap: 8
    })
  }, /*#__PURE__*/React.createElement(HBtn, {
    danger: true,
    onClick: onDelete,
    style: {
      flex: 1,
      justifyContent: 'center'
    }
  }, "Remove ", members.length > 1 ? 'all ' + members.length : 'wire'), /*#__PURE__*/React.createElement(HBtn, {
    onClick: onClose,
    style: {
      justifyContent: 'center'
    }
  }, "Close")));
}
Object.assign(window, {
  WirePanel: WirePanel,
  MultiFieldPanel: MultiFieldPanel,
  SystemPanel: SystemPanel,
  DomainPanel: DomainPanel,
  BulkPanel: BulkPanel,
  FieldPanel: FieldPanel,
  MultiPanel: MultiPanel,
  NodeInspector: NodeInspector,
  NameModal: NameModal
});
