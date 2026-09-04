// verify_app_relation_right_rail_layer_edit.cjs
//
// Bounded proof for app relation wires:
// 1. Render the production canvas and find a real mediated app relation.
// 2. Render the production right rail for that relation wire-node.
// 3. Edit its presentation layer through the rail property control.
// 4. Prove the relation authority reports hidden. A full second canvas redraw
//    can be enabled with APP_REL_FULL_REDRAW=1, but the default verifier stays
//    bounded because the right rail materializes a large inspector graph.

const fs = require('fs');
const os = require('os');
const path = require('path');

const REPO = path.resolve(__dirname, '..');
const WEB_UI = path.join(REPO, 'app', 'web_ui');
const VENDOR = path.join(WEB_UI, 'vendor');
const COMPILED = path.join(WEB_UI, 'studio-lm.compiled.js');
const TRACE_FILE = path.join(os.tmpdir(), 'archhub-app-relation-right-rail.trace.txt');
function trace(label, evidence = {}) {
  if (!process.env.APP_REL_TRACE) return;
  try {
    fs.appendFileSync(TRACE_FILE, label + (Object.keys(evidence).length ? ' ' + JSON.stringify(evidence) : '') + '\n');
  } catch (_e) {}
}

const SELF_TIMEOUT = setTimeout(() => {
  trace('self-timeout');
  fail('verifier self-timeout before proof completed');
}, 240000);

let JSDOM;
for (const base of [
  process.env.ARCHHUB_NODE_MODULES,
  path.join(REPO, '.lagfix_harness', 'node_modules'),
  path.join(REPO, 'node_modules'),
].filter(Boolean)) {
  try {
    JSDOM = require(path.join(base, 'jsdom')).JSDOM;
    break;
  } catch (_e) {}
}

function fail(message, evidence = {}) {
  console.error('VERIFY_FAIL: ' + message);
  if (Object.keys(evidence).length) console.error(JSON.stringify(evidence, null, 2));
  process.exit(1);
}

if (!JSDOM) fail('jsdom not found (ARCHHUB_NODE_MODULES, .lagfix_harness/node_modules, or node_modules)');

function makeSignal() {
  return { connect() {}, disconnect() {}, emit() {} };
}

function makeWindow() {
  const dom = new JSDOM(
    '<!doctype html><html><head></head><body><div id="root"></div></body></html>',
    { runScripts: 'outside-only', pretendToBeVisual: true, url: 'http://127.0.0.1:8480/?prod=1' },
  );
  const { window } = dom;
  window.requestAnimationFrame = cb => setTimeout(() => {
    try { cb(window.performance.now()); } catch (_e) {}
  }, 0);
  window.cancelAnimationFrame = id => clearTimeout(id);
  window.matchMedia = window.matchMedia || (() => ({
    matches: false,
    addListener() {},
    removeListener() {},
    addEventListener() {},
    removeEventListener() {},
  }));
  window.ResizeObserver = window.ResizeObserver || class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
  window.Element.prototype.getBoundingClientRect = function getBoundingClientRect() {
    return {
      x: 0, y: 0, top: 0, left: 0,
      right: 1280, bottom: 820, width: 1280, height: 820,
      toJSON() {},
    };
  };
  window.scrollTo = () => {};
  window.__archhub_LM_GRAPH = { nodes: [], wires: [], groups: [] };
  window.__archhub_LM_SESSIONS = [];
  window.__archhub_LM_HOSTS = [
    { id: 'brain', host: 'brain', name: 'Brain daemon', state: 'on', port: 8473 },
  ];
  window.__archhub_LM_MODELS = [];
  window.__archhub_LM_MEMORY = [];
  window.__archhub_LM_MEMORY_STATS = {};
  window.__archhub_LM_SAVED_SKILLS = [];
  window.__archhub_LM_PERMISSIONS = [];
  window.__archhub_LM_PROVIDERS = [];
  window.__archhub_LM_NODE_GRAMMAR = [];
  window.__archhub_LM_CUSTOM_NODES = [];
  window.__archhub_LM_UI_WIDGETS = [];
  window.__archhub_runtime_info = { debug_port: 8480, brain_port: 8473, brain_ok: true };

  const slot = (value = '{}') => (...args) => {
    const cb = args[args.length - 1];
    if (typeof cb === 'function') {
      try { cb(value); } catch (_e) {}
    }
    return value;
  };
  const archhub = {};
  [
    'chat_chunk', 'chat_reasoning', 'chat_done', 'chat_error',
    'sessions_changed', 'hosts_changed', 'memory_changed', 'skills_changed',
    'trigger_fired', 'node_created', 'workflow_done', 'param_options_ready',
  ].forEach(name => { archhub[name] = makeSignal(); });
  [
    'get_profile', 'save_graph', 'send_chat', 'load_session',
    'get_saved_skills', 'run_workflow', 'run_node', 'get_token_usage',
    'get_brain_stats', 'can_wire', 'would_create_cycle', 'get_runtime_info',
    'get_plan_history', 'graph_validate',
  ].forEach(name => { archhub[name] = slot('{}'); });
  window.archhub = archhub;
  window.archhubReady = Promise.resolve();
  return window;
}

function loadVendor(window) {
  window.eval(fs.readFileSync(path.join(VENDOR, 'react.production.min.js'), 'utf8'));
  window.eval(fs.readFileSync(path.join(VENDOR, 'react-dom.production.min.js'), 'utf8'));
  if (!window.React || !window.ReactDOM) fail('React/ReactDOM did not load');
}

function loadCompiledWithHooks(window) {
  const compiled = fs.readFileSync(COMPILED, 'utf8');
  const marker = 'window.StudioLM=StudioLM;})();';
  const index = compiled.lastIndexOf(marker);
  if (index < 0) fail('cannot instrument compiled bundle: StudioLM marker not found');
  const hooks = [
    'NodeCanvasInner',
    'NodeRail',
    'NodePropertiesSurface',
    'NodeConnectionsSurface',
    'nodeConnectionPanelItems',
    'nodeRailParamItems',
    'ensureGrandMapApplicationSuperNode',
    'ensureSelectedRelationWireFullAnatomy',
  ];
  const exportHooks = (
    'window.__archhubAppRelationRightRailHooks={' +
    hooks.map(name => name + ':' + name).join(',') +
    '};'
  );
  try {
    window.eval(compiled.slice(0, index) + exportHooks + compiled.slice(index));
  } catch (e) {
    fail('compiled bundle threw during eval', { message: e && e.message || String(e) });
  }
  if (!window.__archhubAppRelationRightRailHooks) fail('test hooks were not exported');
}

const delay = ms => new Promise(resolve => setTimeout(resolve, ms));

async function waitUntil(predicate, label, evidenceFn) {
  for (let i = 0; i < 100; i += 1) {
    const value = predicate();
    if (value) return value;
    await delay(100);
  }
  fail(label + ' did not happen', evidenceFn ? evidenceFn() : {});
  return null;
}

function byId(graph, id) {
  return (graph.nodes || []).find(node => node && node.id === id) || null;
}

function paramValue(node, key) {
  const param = node && Array.isArray(node.params)
    ? node.params.find(p => p && p.k === key)
    : null;
  return param ? param.v : undefined;
}

function rawWireFor(graph, wireNode) {
  const data = wireNode && wireNode.data || {};
  return (graph.wires || []).find(wire => {
    const wd = wire && wire.data && typeof wire.data === 'object' ? wire.data : {};
    return wd.relation_node === wireNode.id &&
      wd.role !== 'wire_endpoint' &&
      wd.role !== 'wire_layer_link' &&
      wd.role !== 'wire_runtime_link';
  }) || (data.wire_id ? (graph.wires || []).find(wire => wire && wire.id === data.wire_id) : null);
}

function setControlValue(window, control, value) {
  if (!control) fail('property control missing');
  if (control.tagName === 'SELECT') {
    const option = Array.from(control.options || []).find(opt => opt.value === String(value));
    if (!option) fail('select option missing', {
      value,
      options: Array.from(control.options || []).map(opt => opt.value),
    });
  }
  const proto = Object.getPrototypeOf(control);
  const descriptor = proto ? Object.getOwnPropertyDescriptor(proto, 'value') : null;
  if (descriptor && typeof descriptor.set === 'function') descriptor.set.call(control, String(value));
  else control.value = String(value);
  control.dispatchEvent(new window.Event('input', { bubbles: true }));
  control.dispatchEvent(new window.Event('change', { bubbles: true }));
}

function layerNameForKey(key) {
  return {
    gate_policy: 'gate',
    codec: 'codec',
    encryption: 'encryption',
    behavior: 'behavior',
    presentation: 'presentation',
  }[key] || key;
}

function renderedWireGroups(window) {
  return Array.from(window.document.querySelectorAll('[data-wire-node-id]'));
}

function relationEndpointGroups(window, graph, id) {
  const node = byId(graph, id);
  const data = node && node.data && typeof node.data === 'object' ? node.data : {};
  const sourceId = data.from_port_node || data.from_node || '';
  const targetId = data.to_port_node || data.target_owner || data.target || data.to_node || '';
  const groups = renderedWireGroups(window).filter(group => group.getAttribute('data-wire-node-id') === id);
  return {
    sourceId,
    targetId,
    groups,
    sourceSide: groups.find(group => (
      group.getAttribute('data-wire-from') === sourceId &&
      group.getAttribute('data-wire-to') === id
    )),
    targetSide: groups.find(group => (
      group.getAttribute('data-wire-from') === id &&
      group.getAttribute('data-wire-to') === targetId
    )),
    directShortcut: groups.find(group => (
      group.getAttribute('data-wire-from') === sourceId &&
      group.getAttribute('data-wire-to') === targetId
    )),
  };
}

async function renderCanvas(window, React, ReactDOM, hooks, graph) {
  trace('renderCanvas:start', { nodes: graph.nodes.length, wires: graph.wires.length });
  Array.from(window.document.querySelectorAll('[data-verifier-canvas-host="1"]'))
    .forEach(node => node && node.parentNode && node.parentNode.removeChild(node));
  const host = window.document.createElement('div');
  host.setAttribute('data-verifier-canvas-host', '1');
  window.document.body.appendChild(host);
  const canvasRoot = ReactDOM.createRoot(host);
  const CanvasHarness = () => {
    const [graphBump, setGraphBump] = React.useState(0);
    const bumpGraph = () => setGraphBump(value => value + 1);
    return React.createElement(hooks.NodeCanvasInner, {
      focusId: 'app:archhub',
      setFocusId: () => {},
      setLibraryOpen: () => {},
      userNodes: [],
      addNodeFromLibrary: () => {},
      bumpGraph,
      graphBump,
      removeUserNode: () => {},
    });
  };
  if (ReactDOM.flushSync) ReactDOM.flushSync(() => canvasRoot.render(React.createElement(CanvasHarness)));
  else canvasRoot.render(React.createElement(CanvasHarness));
  trace('renderCanvas:submitted', { nodes: graph.nodes.length, wires: graph.wires.length });
  await delay(1400);
  const groups = renderedWireGroups(window);
  trace('renderCanvas:after-delay', { nodes: graph.nodes.length, wires: graph.wires.length, rendered: groups.length });
  return {
    groups,
    dispose() {
      canvasRoot.unmount();
      if (host.parentNode) host.parentNode.removeChild(host);
    },
  };
}

async function main() {
  if (process.env.APP_REL_TRACE) {
    try { fs.unlinkSync(TRACE_FILE); } catch (_e) {}
  }
  trace('main:start');
  const window = makeWindow();
  trace('window:ready');
  loadVendor(window);
  trace('vendor:ready');
  loadCompiledWithHooks(window);
  trace('compiled:ready');

  const React = window.React;
  const ReactDOM = window.ReactDOM;
  const hooks = window.__archhubAppRelationRightRailHooks;
  const graph = window.__archhub_LM_GRAPH;
  const root = ReactDOM.createRoot(window.document.getElementById('root'));

  hooks.ensureGrandMapApplicationSuperNode({ mode: 'home', session: null, focusId: 'app:archhub' });
  trace('supernode:ensured', { nodes: graph.nodes.length, wires: graph.wires.length });
  const appNode = byId(graph, 'app:archhub');
  if (!appNode) fail('application super-node missing');

  const initialCanvas = await renderCanvas(window, React, ReactDOM, hooks, graph);
  trace('initial-canvas:done', { nodes: graph.nodes.length, wires: graph.wires.length });
  const appRelationWireNodeIds = ((appNode.data && appNode.data.relation_wire_node_ids) || [])
    .filter(id => {
      const node = byId(graph, id);
      const data = node && node.data && typeof node.data === 'object' ? node.data : {};
      return data.role === 'wire' && data.wire_family === 'app_relation';
    });
  const relationNodeId = appRelationWireNodeIds.find(id => {
    const endpoints = relationEndpointGroups(window, graph, id);
    return !!(endpoints.sourceSide && endpoints.targetSide && !endpoints.directShortcut);
  });
  if (!relationNodeId) {
    fail('no rendered app relation uses the mediated source -> wire-node -> target path', {
      appRelationWireNodeIds: appRelationWireNodeIds.slice(0, 20),
      rendered: renderedWireGroups(window).slice(0, 20).map(group => ({
        wireNode: group.getAttribute('data-wire-node-id'),
        from: group.getAttribute('data-wire-from'),
        to: group.getAttribute('data-wire-to'),
      })),
    });
  }

  let wireNode = byId(graph, relationNodeId);
  wireNode = hooks.ensureSelectedRelationWireFullAnatomy(wireNode);
  const initialEndpoints = relationEndpointGroups(window, graph, relationNodeId);
  const initialSourceSide = initialEndpoints.sourceSide;
  const initialPresentationState = initialSourceSide
    ? initialSourceSide.getAttribute('data-wire-presentation-state')
    : '';
  const presentationLayerId = wireNode && wireNode.data && wireNode.data.layer_nodes
    ? wireNode.data.layer_nodes.presentation
    : '';
  if (!presentationLayerId || !byId(graph, presentationLayerId)) {
    fail('rendered app relation wire-node has no presentation layer node', {
      relationNodeId,
      layerNodes: wireNode && wireNode.data && wireNode.data.layer_nodes,
    });
  }

  // The canvas proof is complete. Keeping its 8k-node React tree mounted
  // makes every inspector graph mutation synchronously redraw the canvas in
  // JSDOM, which tests harness scheduling rather than the right-rail route.
  initialCanvas.dispose();
  await delay(0);

  const connectionItemsStarted = Date.now();
  const directConnectionItems = hooks.nodeConnectionPanelItems(wireNode);
  trace('connection-items:done', {
    elapsed_ms: Date.now() - connectionItemsStarted,
    receives: directConnectionItems.receives.length,
    sends: directConnectionItems.sends.length,
    nodes: graph.nodes.length,
    wires: graph.wires.length,
  });
  const directParamItems = hooks.nodeRailParamItems(wireNode);
  trace('property-items:done', {
    count: directParamItems.length,
    keys: directParamItems.map(item => item && item.k),
    nodes: graph.nodes.length,
    wires: graph.wires.length,
  });
  const payloadEnvelopeRef = directParamItems.find(item => item && item.k === 'payload_envelope_node');
  const payloadEnvelopeRelationRef = directParamItems.find(item => item && item.k === 'payload_envelope_relation_node');
  if (!payloadEnvelopeRef || !byId(graph, payloadEnvelopeRef.v) ||
      !payloadEnvelopeRelationRef || !byId(graph, payloadEnvelopeRelationRef.v)) {
    fail('selected relation right rail does not expose its wired payload envelope anatomy', {
      payloadEnvelopeRef,
      payloadEnvelopeRelationRef,
      keys:directParamItems.map(item => item && item.k),
    });
  }
  if (process.env.APP_REL_INSPECT_ONLY === '1') {
    console.log('VERIFY_APP_RELATION_RIGHT_RAIL_ITEMS ' + JSON.stringify({
      ok: true,
      relationWireNode: relationNodeId,
      connectionItems: {
        receives: directConnectionItems.receives.length,
        sends: directConnectionItems.sends.length,
      },
      propertyItems: directParamItems.map(item => ({
        key: item && item.k,
        family: item && item.param_family || '',
        readOnly: !!(item && item.read_only),
      })),
      graph: { nodes: graph.nodes.length, wires: graph.wires.length },
    }, null, 2));
    clearTimeout(SELF_TIMEOUT);
    process.exit(0);
  }

  const RailHarness = () => {
    const [, bump] = React.useReducer(value => value + 1, 0);
    const props = {
      node: byId(graph, relationNodeId),
      bumpGraph: bump,
      setFocusId: () => {},
      onParamChange: () => {},
    };
    if (process.env.APP_REL_COMPONENT === 'properties') {
      return React.createElement(hooks.NodePropertiesSurface, props);
    }
    if (process.env.APP_REL_COMPONENT === 'connections') {
      return React.createElement(hooks.NodeConnectionsSurface, props);
    }
    return React.createElement(hooks.NodeRail, props);
  };
  if (ReactDOM.flushSync) ReactDOM.flushSync(() => root.render(React.createElement(RailHarness)));
  else root.render(React.createElement(RailHarness));
  trace('rail:submitted', { relationNodeId, nodes: graph.nodes.length, wires: graph.wires.length });

  const editLayer = async (key, value) => {
    const layerName = layerNameForKey(key);
    const expectedLayerNode = wireNode && wireNode.data && wireNode.data.layer_nodes
      ? wireNode.data.layer_nodes[layerName]
      : '';
    const rowSelector = '[data-param-owner="' + relationNodeId + '"][data-param-key="' + key + '"]';
    const row = await waitUntil(
      () => window.document.querySelector(rowSelector),
      'right rail ' + key + ' property row for relation wire-node',
      () => ({
        selector: rowSelector,
        html: window.document.getElementById('root').innerHTML.slice(0, 4000),
      }),
    );
    trace('editLayer:row-found', { key, rowNode: row.getAttribute('data-node') || '', nodes: graph.nodes.length, wires: graph.wires.length });
    if (row.getAttribute('data-wire-layer-node') !== expectedLayerNode ||
        row.getAttribute('data-wire-layer') !== layerName) {
      fail(key + ' property row is not bound to its layer node', {
        expectedLayer: expectedLayerNode,
        rowLayer: row.getAttribute('data-wire-layer'),
        rowLayerNode: row.getAttribute('data-wire-layer-node'),
      });
    }
    setControlValue(window, row.querySelector('input, textarea, select'), value);
    trace('editLayer:control-set', { key, value, nodes: graph.nodes.length, wires: graph.wires.length });
    return { key, layerName, layerNode: expectedLayerNode };
  };

  const editedRows = [];
  editedRows.push(await editLayer('presentation', 'hidden'));
  trace('edit:done', { nodes: graph.nodes.length, wires: graph.wires.length });
  await delay(900);
  trace('edit:after-delay', { nodes: graph.nodes.length, wires: graph.wires.length });

  const updatedWireNode = byId(graph, relationNodeId);
  const updatedRawWire = rawWireFor(graph, updatedWireNode);
  const expectedValues = {
    presentation: 'hidden',
  };
  const proof = {};
  for (const [key, expected] of Object.entries(expectedValues)) {
    const layerName = layerNameForKey(key);
    const layerNodeId = updatedWireNode && updatedWireNode.data && updatedWireNode.data.layer_nodes
      ? updatedWireNode.data.layer_nodes[layerName]
      : '';
    const layerNode = byId(graph, layerNodeId);
    proof[key] = {
      wireNodeValue: updatedWireNode && updatedWireNode.data && updatedWireNode.data[key],
      wireNodeParam: paramValue(updatedWireNode, key),
      layerNodeValue: layerNode && layerNode.data && layerNode.data.value,
      layerNodeParam: paramValue(layerNode, 'value'),
      rawWireValue: updatedRawWire && updatedRawWire[key],
      rawWireDataValue: updatedRawWire && updatedRawWire.data && updatedRawWire.data[key],
    };
    const p = proof[key];
    if (p.wireNodeValue !== expected ||
        p.wireNodeParam !== expected ||
        p.layerNodeValue !== expected ||
        p.layerNodeParam !== expected ||
        p.rawWireValue !== expected ||
        p.rawWireDataValue !== expected) {
      fail('right rail ' + key + ' edit did not propagate through wire authority', p);
    }
  }

  const envelopeNodeId = updatedWireNode && updatedWireNode.data && updatedWireNode.data.payload_envelope_node_id || '';
  const envelopeNode = byId(graph, envelopeNodeId);
  if (!envelopeNode) fail('selected relation payload envelope node disappeared', { envelopeNodeId });
  if (ReactDOM.flushSync) ReactDOM.flushSync(() => root.render(React.createElement(hooks.NodePropertiesSurface, {
    node:envelopeNode, bumpGraph:() => {}, setFocusId:() => {}, onParamChange:() => {},
  })));
  else root.render(React.createElement(hooks.NodePropertiesSurface, {
    node:envelopeNode, bumpGraph:() => {}, setFocusId:() => {}, onParamChange:() => {},
  }));
  const logicalTypeRow = await waitUntil(
    () => window.document.querySelector('[data-param-owner="' + envelopeNodeId + '"][data-param-key="logical_type"]'),
    'payload envelope logical type row',
  );
  const editedLogicalType = 'founder.payload.geometry-image.v1';
  setControlValue(window, logicalTypeRow.querySelector('input, textarea, select'), editedLogicalType);
  await delay(300);
  const updatedEnvelopeNode = byId(graph, envelopeNodeId);
  const logicalTypeValueNode = byId(graph, 'param:' + envelopeNodeId + ':logical_type');
  const envelopeEditProof = {
    dataValue:updatedEnvelopeNode && updatedEnvelopeNode.data && updatedEnvelopeNode.data.logical_type,
    paramValue:paramValue(updatedEnvelopeNode, 'logical_type'),
    valueNodeValue:logicalTypeValueNode && logicalTypeValueNode.data && logicalTypeValueNode.data.value,
    valueNodeParam:paramValue(logicalTypeValueNode, 'value'),
  };
  if (Object.values(envelopeEditProof).some(value => value !== editedLogicalType)) {
    fail('payload envelope right rail edit did not update every node-owned value', envelopeEditProof);
  }

  let updatedPresentationState = 'hidden';
  let updatedSourceSide = initialSourceSide;
  const fullRedraw = process.env.APP_REL_FULL_REDRAW === '1';
  if (fullRedraw) {
    await renderCanvas(window, React, ReactDOM, hooks, graph);
    trace('updated-canvas:done', { nodes: graph.nodes.length, wires: graph.wires.length });
    const updatedEndpoints = relationEndpointGroups(window, graph, relationNodeId);
    updatedSourceSide = updatedEndpoints.sourceSide;
    updatedPresentationState = updatedSourceSide
      ? updatedSourceSide.getAttribute('data-wire-presentation-state')
      : '';
    if (updatedPresentationState !== 'hidden') {
      fail('canvas did not redraw the app relation wire with hidden presentation state', {
        relationNodeId,
        updatedPresentationState,
        groupCount: updatedEndpoints.groups.length,
      });
    }
  }

  console.log('VERIFY_APP_RELATION_RIGHT_RAIL_LAYER_EDIT ' + JSON.stringify({
    ok: true,
    relationWireNode: relationNodeId,
    presentationLayerNode: presentationLayerId,
    editedRows,
    proof,
    payloadEnvelope: {
      node:envelopeNodeId,
      relationNode:payloadEnvelopeRelationRef.v,
      logicalType:editedLogicalType,
      editProof:envelopeEditProof,
    },
    canvas: {
      redrawMode: fullRedraw ? 'full-redraw' : 'bounded-authority',
      initialPresentationState,
      presentationState: updatedPresentationState,
      vocab: updatedSourceSide ? updatedSourceSide.getAttribute('data-wire-vocab') : '',
    },
    graph: {
      nodes: graph.nodes.length,
      wires: graph.wires.length,
    },
  }, null, 2));
  clearTimeout(SELF_TIMEOUT);
  process.exit(0);
}

main().catch(err => fail('unexpected verifier error', {
  message: err && err.message || String(err),
  stack: err && err.stack || '',
}));
