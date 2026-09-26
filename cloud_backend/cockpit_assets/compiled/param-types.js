// param-types.jsx — THE parameter type registry. One vocabulary for both graphs.
//
// The cockpit's grand map and the app's session canvas each grew their own idea of what a
// parameter type is (cockpit: string/number/boolean/color/trigger — app: number/toggle/text/
// menu/colour/elements/view/…). Two names for one concept is exactly the drift this project
// keeps paying for, so the registry lives here and both read it: a "toggle" is the same
// colour and the same socket in the cockpit and in Studio, and adding a type adds it to both.
//
// COLOUR encodes the data type. SHAPE encodes cardinality — round = one value, diamond = a
// list. That is Unreal Blueprint's convention, and it means connection legality is readable
// without a legend.
(function () {
  var T = window.AH;
  var PM_TYPES = window.ArchHubTheme.derive(function (T) {
    return {
      number: {
        label: 'Number',
        glyph: '#',
        col: T.warn,
        wire: false,
        def: 0
      },
      toggle: {
        label: 'Toggle',
        glyph: '◐',
        col: T.purple,
        wire: false,
        def: false
      },
      text: {
        label: 'Text',
        glyph: 'T',
        col: T.inkSoft,
        wire: false,
        def: ''
      },
      menu: {
        label: 'Menu',
        glyph: '≡',
        col: T.blue,
        wire: false,
        def: ''
      },
      colour: {
        label: 'Colour',
        glyph: '◉',
        col: T.ok,
        wire: false,
        def: '#d97757'
      },
      elements: {
        label: 'Elements',
        glyph: '▭',
        col: T.accent,
        wire: true
      },
      view: {
        label: 'View',
        glyph: '◱',
        col: T.cyan,
        wire: true
      },
      dims: {
        label: 'Annotation',
        glyph: '↔',
        col: T.ok,
        wire: true
      },
      file: {
        label: 'File',
        glyph: '⎘',
        col: T.ok,
        wire: true
      },
      any: {
        label: 'Any',
        glyph: '✳',
        col: T.inkMuted,
        wire: true
      }
    };
  });

  // canvas wire-type names → the registry, so a wire on the map and a socket in a panel agree
  var PM_WIRE = window.ArchHubTheme.derive(function (T) {
    return {
      view: T.cyan,
      selection: T.cyan,
      walls: T.accent,
      doors: T.accent,
      sheets: T.accent,
      intent: T.purple,
      prediction: T.purple,
      trace: T.inkSoft,
      dims: T.ok,
      file: T.ok,
      any: T.inkSoft,
      number: T.warn,
      text: T.inkSoft,
      string: T.inkSoft,
      "boolean": T.purple,
      exec: T.accent
    };
  });

  // the cockpit's older type names → registry names
  var PM_ALIAS = {
    string: 'text',
    "boolean": 'toggle',
    color: 'colour',
    trigger: 'any'
  };
  var pmType = function pmType(t) {
    return PM_TYPES[t] || PM_TYPES[PM_ALIAS[t]] || PM_TYPES.any;
  };
  var Socket = function Socket(_ref) {
    var type = _ref.type,
      list = _ref.list,
      filled = _ref.filled,
      _ref$size = _ref.size,
      size = _ref$size === void 0 ? 9 : _ref$size;
    var c = pmType(type).col;
    return /*#__PURE__*/React.createElement("span", {
      style: {
        width: size,
        height: size,
        flexShrink: 0,
        display: 'inline-block',
        background: filled ? c : 'transparent',
        border: "1.5px solid ".concat(c),
        borderRadius: list ? 2 : '50%',
        transform: list ? 'rotate(45deg)' : 'none'
      }
    });
  };

  // The parameters a connection carries are NOT declared here: the server holds the one list
  // (universal_pipeline.WIRE_PARAMETER_SPECS) and serves it with the node library; studio.html and
  // cockpit.html set window.WIRE_PARAMS from it. The run applies every row it lists.

  Object.assign(window, {
    PM_TYPES: PM_TYPES,
    PM_WIRE: PM_WIRE,
    PM_ALIAS: PM_ALIAS,
    pmType: pmType,
    Socket: Socket
  });
})();
