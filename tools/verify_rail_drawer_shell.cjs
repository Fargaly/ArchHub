// Proves the shared Search/Share/Nodes/Skills drawer chrome is projected from
// graph UI nodes and its visible close interactions are ui_action wire routes.

const fs = require('fs');
const path = require('path');
const childProcess = require('child_process');

const REPO = path.resolve(__dirname, '..');
const WEB_UI = path.join(REPO, 'app', 'web_ui');
const VENDOR = path.join(WEB_UI, 'vendor');
const COMPILED = path.join(WEB_UI, 'studio-lm.compiled.js');
const SELF_TIMEOUT = setTimeout(() => fail('verifier self-timeout'), 60000);

let JSDOM;
for (const base of [
  process.env.ARCHHUB_NODE_MODULES,
  path.join(REPO, '.lagfix_harness', 'node_modules'),
  path.join(REPO, 'node_modules'),
].filter(Boolean)) {
  try { JSDOM = require(path.join(base, 'jsdom')).JSDOM; break; } catch (_e) {}
}

function fail(message, evidence = {}) {
  console.error('VERIFY_FAIL: ' + message);
  if (Object.keys(evidence).length) console.error(JSON.stringify(evidence, null, 2));
  process.exit(1);
}
function trace(label, evidence = {}) {
  if (!process.env.DRAWER_TRACE) return;
  console.error('VERIFY_TRACE: ' + label + ' ' + JSON.stringify(evidence));
}
if (!JSDOM) fail('jsdom not found');

function loadSurface() {
  const py = `
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path('app').resolve()))
from workflows.grand_map_ui import grand_map_ui_surface
print(json.dumps(grand_map_ui_surface('rail-drawer-shell')))
`;
  return JSON.parse(childProcess.execFileSync('python', ['-c', py], {
    cwd: REPO, encoding: 'utf8', maxBuffer: 20 * 1024 * 1024,
  }));
}

function makeSignal() { return { connect() {}, disconnect() {}, emit() {} }; }
function makeWindow(surface) {
  const dom = new JSDOM(
    '<!doctype html><html><head></head><body><div id="root"></div></body></html>',
    { runScripts:'outside-only', pretendToBeVisual:true, url:'http://127.0.0.1:8480/?prod=1' },
  );
  const { window } = dom;
  window.requestAnimationFrame = cb => setTimeout(() => cb(window.performance.now()), 0);
  window.cancelAnimationFrame = id => clearTimeout(id);
  window.matchMedia = () => ({ matches:false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} });
  window.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} };
  window.Element.prototype.getBoundingClientRect = () => ({
    x:0, y:0, top:0, left:0, right:1600, bottom:1000, width:1600, height:1000, toJSON() {},
  });
  window.scrollTo = () => {};
  window.__drawer_event_counts = {};
  const nativeDispatch = window.dispatchEvent.bind(window);
  window.dispatchEvent = event => {
    const type = event && event.type || 'unknown';
    window.__drawer_event_counts[type] = (window.__drawer_event_counts[type] || 0) + 1;
    if (window.__drawer_event_counts[type] > 20000) {
      fail('drawer event loop exceeded bound', { type, counts:window.__drawer_event_counts });
    }
    return nativeDispatch(event);
  };
  window.__archhub_LM_GRAPH = { nodes:[], wires:[], groups:[] };
  window.__archhub_LM_SESSIONS = [];
  window.__archhub_LM_HOSTS = [];
  window.__archhub_LM_MODELS = [];
  window.__archhub_LM_MEMORY = [];
  window.__archhub_LM_MEMORY_STATS = {};
  window.__archhub_LM_SAVED_SKILLS = [];
  window.__archhub_LM_PERMISSIONS = [];
  window.__archhub_LM_PROVIDERS = [];
  window.__archhub_LM_NODE_GRAMMAR = [];
  window.__archhub_LM_CUSTOM_NODES = [];
  window.__archhub_LM_UI_WIDGETS = [];
  const slot = (value = '{}') => (...args) => {
    const cb = args[args.length - 1];
    if (typeof cb === 'function') cb(value);
    return value;
  };
  const archhub = {};
  ['chat_chunk','chat_reasoning','chat_done','chat_error','sessions_changed','hosts_changed','memory_changed','skills_changed','trigger_fired','node_created','workflow_done','param_options_ready']
    .forEach(name => { archhub[name] = makeSignal(); });
  archhub.get_grand_map_ui_surface = (_name, cb) => {
    const raw = JSON.stringify(surface);
    if (typeof cb === 'function') cb(raw);
    return raw;
  };
  ['get_profile','save_graph','send_chat','load_session','get_saved_skills','run_workflow','run_node','get_token_usage','get_brain_stats','can_wire','would_create_cycle','get_runtime_info','graph_validate']
    .forEach(name => { archhub[name] = slot('{}'); });
  window.archhub = archhub;
  window.archhubReady = Promise.resolve();
  return window;
}

function loadBundle(window) {
  window.eval(fs.readFileSync(path.join(VENDOR, 'react.production.min.js'), 'utf8'));
  window.eval(fs.readFileSync(path.join(VENDOR, 'react-dom.production.min.js'), 'utf8'));
  const compiled = fs.readFileSync(COMPILED, 'utf8');
  const marker = 'window.StudioLM=StudioLM;})();';
  const index = compiled.lastIndexOf(marker);
  if (index < 0) fail('cannot instrument compiled bundle');
  const exportHooks = 'window.__railDrawerHooks={RailDrawerShellSurface:RailDrawerShellSurface,ensureSelectedRelationWireFullAnatomy:ensureSelectedRelationWireFullAnatomy};';
  window.eval(compiled.slice(0, index) + exportHooks + compiled.slice(index));
}

const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
async function waitFor(window, predicate, label) {
  for (let i = 0; i < 80; i += 1) {
    const value = predicate();
    if (value) return value;
    await delay(80);
  }
  fail(label + ' did not become ready', { html:window.document.body.innerHTML.slice(0, 3000) });
}

function actionCoverage(graph, ownerId) {
  const actions = graph.nodes.filter(node => node && node.data && node.data.role === 'ui_action' && node.data.owner === ownerId);
  const actionIds = new Set(actions.map(node => node.id));
  const wireNodes = graph.nodes.filter(node => {
    const data = node && node.data || {};
    return data.role === 'wire' && data.wire_family === 'ui_action' &&
      (actionIds.has(data.source_owner) || actionIds.has(data.target_owner));
  });
  return { actions, wireNodes };
}

async function main() {
  trace('surface:start');
  const surface = loadSurface();
  trace('surface:done', { nodes:surface.nodes && surface.nodes.length });
  if (!surface.ok) fail('rail drawer authority surface failed', surface);
  const window = makeWindow(surface);
  trace('window:done');
  loadBundle(window);
  trace('bundle:done');
  const nativeSetParam = window.ahSetUiNodeParam;
  window.__drawer_param_sets = 0;
  window.ahSetUiNodeParam = (...args) => {
    window.__drawer_param_sets += 1;
    if (window.__drawer_param_sets > 30000) {
      fail('drawer parameter loop exceeded bound', {
        count:window.__drawer_param_sets,
        last:args.slice(0, 3),
        events:window.__drawer_event_counts,
      });
    }
    return nativeSetParam(...args);
  };
  const React = window.React;
  const ReactDOM = window.ReactDOM;
  const graph = window.__archhub_LM_GRAPH;
  const Shell = window.__railDrawerHooks.RailDrawerShellSurface;
  const events = [];
  window.addEventListener('lm-ui-node-action', event => {
    if (event && event.detail && event.detail.action === 'rail.drawer.close') events.push(event.detail);
  });

  const render = (panel, title, testid) => ReactDOM.render(
    React.createElement(Shell, {
      panel,
      meta:{ title, testid },
      body:React.createElement('div', { 'data-testid':'drawer-body-proof' }, 'BODY'),
    }),
    window.document.getElementById('root'),
  );
  trace('render:search:start');
  render('search', 'Search', 'rail-search');
  trace('render:search:returned');
  const overlay = await waitFor(window, () => window.document.querySelector('[data-uisurface="rail-drawer-shell"]'), 'drawer overlay');
  trace('overlay:ready');
  const frame = window.document.querySelector('[data-node="ui:grandmap:rail-drawer-frame"]');
  const close = window.document.querySelector('[data-testid="rail-drawer-close"]');
  const body = window.document.querySelector('[data-testid="drawer-body-proof"]');
  if (!frame || !close || !body) fail('drawer graph elements missing');
  await waitFor(window, () => frame.getAttribute('data-testid') === 'rail-search' &&
    frame.getAttribute('data-rail-drawer') === 'search', 'dynamic search drawer identity');
  trace('identity:ready');
  if (overlay.getAttribute('data-testid') !== 'rail-drawer-overlay' ||
      frame.getAttribute('data-testid') !== 'rail-search' ||
      frame.getAttribute('data-rail-drawer') !== 'search') {
    fail('legacy drawer DOM contract changed', {
      overlay:overlay.getAttribute('data-testid'),
      frame:frame.getAttribute('data-testid'),
      panel:frame.getAttribute('data-rail-drawer'),
    });
  }
  if (window.document.querySelector('.ah-rail-drawer-title-node').textContent !== 'Search') fail('bound title missing');
  const closeOwner = (graph.nodes || []).find(node => node && node.id === 'ui:grandmap:rail-drawer-close');
  const closeRoute = closeOwner && closeOwner.data && closeOwner.data.action_routes_by_key &&
    closeOwner.data.action_routes_by_key.action;
  const closeRouteAction = closeRoute && (graph.nodes || []).find(node => node && node.id === closeRoute.action_node_id);
  const closeRouteHandler = closeRoute && (graph.nodes || []).find(node => node && node.id === closeRoute.action_handler_node_id);
  if (!closeRoute || !closeRouteAction || !closeRouteHandler) {
    fail('rail drawer close control has no pre-hydrated action route', {
      closeRoute,
      closeOwner:closeOwner && closeOwner.data,
    });
  }

  frame.dispatchEvent(new window.MouseEvent('click', { bubbles:true }));
  trace('frame:clicked');
  if (events.length) fail('frame click leaked into backdrop close action');
  close.dispatchEvent(new window.MouseEvent('click', { bubbles:true }));
  trace('close:clicked');
  await waitFor(window, () => events.length === 1, 'close action');
  trace('close:event');
  const closeCoverage = actionCoverage(graph, 'ui:grandmap:rail-drawer-close');
  if (!closeCoverage.actions.length || closeCoverage.wireNodes.length < 2) {
    fail('close button did not materialize action nodes and wires', {
      actions:closeCoverage.actions.map(node => node.id),
      wires:closeCoverage.wireNodes.map(node => node.id),
    });
  }
  const restingAnatomy = closeCoverage.wireNodes.map(node => node.data && node.data.anatomy_mode || 'none');
  if (restingAnatomy.some(mode => mode !== 'none')) {
    fail('close action wires must defer anatomy until selected', { restingAnatomy });
  }
  const promotedCloseWire = window.__railDrawerHooks.ensureSelectedRelationWireFullAnatomy(closeCoverage.wireNodes[0]);
  if (!promotedCloseWire || Object.keys(promotedCloseWire.data && promotedCloseWire.data.layer_nodes || {}).length !== 13) {
    fail('selected close action wire missing 13 layers', {
      wireNode:promotedCloseWire && promotedCloseWire.id,
      layerNodes:promotedCloseWire && promotedCloseWire.data && promotedCloseWire.data.layer_nodes,
    });
  }

  overlay.dispatchEvent(new window.MouseEvent('click', { bubbles:true }));
  trace('overlay:clicked');
  await waitFor(window, () => events.length === 2, 'backdrop action');
  render('share', 'Share', 'rail-share-drawer');
  trace('render:share:returned');
  await waitFor(window, () => frame.getAttribute('data-testid') === 'rail-share-drawer', 'dynamic drawer identity');
  if (frame.getAttribute('data-rail-drawer') !== 'share' ||
      window.document.querySelector('.ah-rail-drawer-title-node').textContent !== 'Share') {
    fail('dynamic drawer state did not flow through graph nodes');
  }

  const requiredIds = [
    'ui:grandmap:rail-drawer-shell','ui:grandmap:rail-drawer-frame','ui:grandmap:rail-drawer-header',
    'ui:grandmap:rail-drawer-title','ui:grandmap:rail-drawer-spacer','ui:grandmap:rail-drawer-close',
    'ui:grandmap:rail-drawer-body',
  ];
  const missingIds = requiredIds.filter(id => !graph.nodes.some(node => node && node.id === id));
  if (missingIds.length) fail('drawer graph node coverage incomplete', { missingIds });
  console.log('VERIFY_RAIL_DRAWER_SHELL ' + JSON.stringify({
    ok:true,
    nodeIds:requiredIds,
    closeActionNode:closeCoverage.actions[0].id,
    closeWireNodes:closeCoverage.wireNodes.map(node => node.id),
    restingAnatomy,
    selectedLayerCount:Object.keys(promotedCloseWire.data.layer_nodes || {}).length,
    events:events.map(event => ({ node:event.node_id, reason:event.args && event.args.reason })),
    dynamic:{ panel:frame.getAttribute('data-rail-drawer'), testid:frame.getAttribute('data-testid') },
    graph:{ nodes:graph.nodes.length, wires:graph.wires.length },
  }, null, 2));
  clearTimeout(SELF_TIMEOUT);
  process.exit(0);
}

main().catch(error => fail(error && error.stack || String(error)));
