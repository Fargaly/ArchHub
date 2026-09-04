// Proves UI composition is rendered from relation nodes, not children[] arrays.
const fs = require('fs');
const path = require('path');

const REPO = path.resolve(__dirname, '..');
const WEB_UI = path.join(REPO, 'app', 'web_ui');
const VENDOR = path.join(WEB_UI, 'vendor');
const COMPILED = path.join(WEB_UI, 'studio-lm.compiled.js');
const SELF_TIMEOUT = setTimeout(() => fail('verifier timeout'), 30000);

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

if (!JSDOM) fail('jsdom not found');

const dom = new JSDOM(
  '<!doctype html><html><body><div id="root"></div></body></html>',
  { runScripts:'outside-only', pretendToBeVisual:true, url:'http://127.0.0.1:8480/?prod=1' },
);
const { window } = dom;
window.requestAnimationFrame = fn => setTimeout(fn, 0);
window.cancelAnimationFrame = id => clearTimeout(id);
window.matchMedia = () => ({ matches:false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} });
window.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} };
window.scrollTo = () => {};
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
window.archhub = {};
window.archhubReady = Promise.resolve();

window.eval(fs.readFileSync(path.join(VENDOR, 'react.production.min.js'), 'utf8'));
window.eval(fs.readFileSync(path.join(VENDOR, 'react-dom.production.min.js'), 'utf8'));
const compiled = fs.readFileSync(COMPILED, 'utf8');
const marker = 'window.StudioLM=StudioLM;})();';
const index = compiled.lastIndexOf(marker);
if (index < 0) fail('cannot instrument compiled bundle');
const hookNames = ['UiNodeSurface', 'ensureSelectedRelationWireFullAnatomy', 'recordGraphOperationNode'];
const exportHooks = 'window.__uiChildHooks={' + hookNames.map(name => name + ':' + name).join(',') + '};';
window.eval(compiled.slice(0, index) + exportHooks + compiled.slice(index));

const graph = window.__archhub_LM_GRAPH;
const parentId = 'ui:authority:parent';
const childAId = 'ui:authority:child-a';
const childBId = 'ui:authority:child-b';
const slotHostId = 'ui:authority:slot-host';
const surfaceRefHostId = 'ui:authority:surface-ref-host';
const bindingSourceAId = 'value:authority:binding-a';
const bindingSourceBId = 'value:authority:binding-b';
const bindingTargetId = 'ui:authority:binding-target';
graph.nodes.push(
  {
    id:parentId, type:'ui.element', cat:'ui', title:'authority parent',
    data:{ tag:'div', children:[childAId] }, config:{}, params:[],
    ins:[{ id:'parent', label:'parent', t:'ui' }], outs:[{ id:'child', label:'child', t:'ui' }],
  },
  {
    id:childAId, type:'ui.element', cat:'ui', title:'child A',
    data:{ tag:'span', text:'CHILD_A' }, config:{}, params:[],
    ins:[{ id:'parent', label:'parent', t:'ui' }], outs:[{ id:'child', label:'child', t:'ui' }],
  },
  {
    id:childBId, type:'ui.element', cat:'ui', title:'child B',
    data:{ tag:'span', text:'CHILD_B' }, config:{}, params:[],
    ins:[{ id:'parent', label:'parent', t:'ui' }], outs:[{ id:'child', label:'child', t:'ui' }],
  },
  {
    id:slotHostId, type:'ui.element', cat:'ui', title:'slot host',
    data:{ tag:'div', render_slot:'slot:authority:a' }, config:{}, params:[],
    ins:[{ id:'parent', label:'parent', t:'ui' }], outs:[{ id:'child', label:'child', t:'ui' }],
  },
  {
    id:surfaceRefHostId, type:'ui.element', cat:'ui', title:'surface ref host',
    data:{ tag:'div', surface_ref:'authority-surface-a' }, config:{}, params:[],
    ins:[{ id:'parent', label:'parent', t:'ui' }], outs:[{ id:'child', label:'child', t:'ui' }],
  },
  {
    id:bindingSourceAId, type:'data.constant', kind:'value', cat:'data', title:'binding A',
    data:{ value:'BINDING_A' }, config:{ value:'BINDING_A' }, params:[{ k:'value', type:'text', v:'BINDING_A' }],
    ins:[], outs:[{ id:'value', label:'value', t:'text' }],
  },
  {
    id:bindingSourceBId, type:'data.constant', kind:'value', cat:'data', title:'binding B',
    data:{ value:'BINDING_B' }, config:{ value:'BINDING_B' }, params:[{ k:'value', type:'text', v:'BINDING_B' }],
    ins:[], outs:[{ id:'value', label:'value', t:'text' }],
  },
  {
    id:bindingTargetId, type:'ui.element', cat:'ui', title:'binding target',
    data:{ tag:'span', bind:bindingSourceAId }, config:{}, params:[],
    ins:[{ id:'parent', label:'parent', t:'ui' }], outs:[{ id:'child', label:'child', t:'ui' }],
  },
);
graph.wires.push({
  id:'w:legacy-binding-projection',
  from:{ node:bindingSourceAId, port:'value' },
  to:{ node:bindingTargetId, port:'binding:bind' },
  data:{
    role:'ui_binding_relation', relation:'binds',
    source_node:bindingSourceAId, target_node:bindingTargetId,
    binding_key:'bind',
  },
});

const byId = id => graph.nodes.find(node => node && node.id === id);
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
async function waitFor(predicate, label) {
  for (let i = 0; i < 100; i += 1) {
    const value = predicate();
    if (value) return value;
    await delay(25);
  }
  fail(label + ' did not become true', { html:window.document.body.innerHTML.slice(0, 2000) });
}

async function main() {
  const root = window.ReactDOM.createRoot(window.document.getElementById('root'));
  root.render(window.React.createElement(window.React.Fragment, null,
    window.React.createElement(window.__uiChildHooks.UiNodeSurface, {
      rootId:parentId,
      surface:'ui-child-authority-verifier',
    }),
    window.React.createElement(window.__uiChildHooks.UiNodeSurface, {
      rootId:slotHostId,
      surface:'ui-render-slot-authority-verifier',
      renderSlots:{
        'slot:authority:a':window.React.createElement('span', { 'data-slot-proof':'a' }, 'SLOT_A'),
        'slot:authority:b':window.React.createElement('span', { 'data-slot-proof':'b' }, 'SLOT_B'),
      },
    }),
    window.React.createElement(window.__uiChildHooks.UiNodeSurface, {
      rootId:bindingTargetId,
      surface:'ui-binding-authority-verifier',
    }),
    window.React.createElement(window.__uiChildHooks.UiNodeSurface, {
      rootId:surfaceRefHostId,
      surface:'ui-surface-ref-authority-verifier',
      renderSlots:{
        'slot:surface-ref:authority-surface-a':window.React.createElement('span', { 'data-surface-ref-proof':'a' }, 'SURFACE_A'),
        'slot:surface-ref:authority-surface-b':window.React.createElement('span', { 'data-surface-ref-proof':'b' }, 'SURFACE_B'),
      },
    }),
  ));
  await waitFor(() => window.document.querySelector('[data-node="' + childAId + '"]'), 'child A render');
  await waitFor(() => window.document.querySelector('[data-slot-proof="a"]'), 'slot A render');
  await waitFor(() => {
    const el = window.document.querySelector('[data-node="' + bindingTargetId + '"]');
    return el && el.textContent === 'BINDING_A';
  }, 'binding A render');
  await waitFor(() => window.document.querySelector('[data-surface-ref-proof="a"]'), 'surface-ref A render');

  const relationWire = graph.wires.find(wire => {
    const data = wire && wire.data && typeof wire.data === 'object' ? wire.data : {};
    return data.role === 'ui_child_relation' && data.source_owner === parentId;
  });
  const relationNodeId = relationWire && relationWire.data && relationWire.data.relation_node;
  let relationNode = byId(relationNodeId);
  if (!relationWire || !relationNode) fail('child relation node missing', { relationWire, relationNodeId });
  const endpoints = graph.wires.filter(wire => wire && wire.data && wire.data.role === 'wire_endpoint' && wire.data.relation_node === relationNodeId);
  if (endpoints.length !== 2) fail('child relation is not intermediary between both endpoints', { endpoints });

  relationNode = window.__uiChildHooks.ensureSelectedRelationWireFullAnatomy(relationNode);
  const keys = new Set((relationNode.params || []).map(param => param && param.k));
  for (const key of ['target_owner', 'child_order', 'gate_policy', 'behavior', 'presentation']) {
    if (!keys.has(key)) fail('inspector parameter missing from child relation', { key, keys:Array.from(keys) });
  }

  window.ahSetUiNodeParam(relationNodeId, 'target_owner', childBId);
  await waitFor(() => window.document.querySelector('[data-node="' + childBId + '"]'), 'retargeted child B render');
  if (window.document.querySelector('[data-node="' + childAId + '"]')) fail('child A remained after relation retarget');
  if (JSON.stringify(byId(parentId).data.children) !== JSON.stringify([childAId])) {
    fail('compatibility children projection changed during relation retarget');
  }

  window.ahSetUiNodeParam(relationNodeId, 'gate_policy', 'deny');
  await waitFor(() => !window.document.querySelector('[data-node="' + childBId + '"]'), 'deny gate removal');

  window.ahSetUiNodeParam(relationNodeId, 'gate_policy', 'allow-if-parent-visible');
  graph.wires = graph.wires.filter(wire => wire && wire.id !== relationWire.id);
  window.dispatchEvent(new window.CustomEvent('lm-graph-bump'));
  await waitFor(() => window.document.querySelector('[data-node="' + childBId + '"]'), 'child survives projection deletion');
  window.__uiChildHooks.recordGraphOperationNode(graph, 'node.delete', { target_ids:[relationNodeId] }, { wireTargets:false });
  graph.nodes = graph.nodes.filter(node => node && node.id !== relationNodeId);
  window.dispatchEvent(new window.CustomEvent('lm-graph-bump'));
  await delay(100);
  if (window.document.querySelector('[data-node="' + childAId + '"]') || window.document.querySelector('[data-node="' + childBId + '"]')) {
    fail('deleted child relation node fell back to children[]');
  }

  const mountWire = graph.wires.find(wire => {
    const data = wire && wire.data && typeof wire.data === 'object' ? wire.data : {};
    return data.wire_family === 'ui_render_slot_mount' && data.role !== 'wire_endpoint' && data.target_owner === slotHostId;
  });
  const mountNodeId = mountWire && mountWire.data && mountWire.data.relation_node;
  let mountNode = byId(mountNodeId);
  if (!mountWire || !mountNode) fail('render-slot mount relation missing', { mountWire, mountNodeId });
  const mountEndpoints = graph.wires.filter(wire => wire && wire.data && wire.data.role === 'wire_endpoint' && wire.data.relation_node === mountNodeId);
  if (mountEndpoints.length !== 2) fail('render-slot relation does not mediate both endpoints', { mountEndpoints });
  mountNode = window.__uiChildHooks.ensureSelectedRelationWireFullAnatomy(mountNode);
  const mountKeys = new Set((mountNode.params || []).map(param => param && param.k));
  for (const key of ['render_slot', 'gate_policy', 'behavior', 'presentation']) {
    if (!mountKeys.has(key)) fail('render-slot inspector parameter missing', { key, keys:Array.from(mountKeys) });
  }
  window.ahSetUiNodeParam(mountNodeId, 'render_slot', 'slot:authority:b');
  await waitFor(() => window.document.querySelector('[data-slot-proof="b"]'), 'retargeted slot B render');
  if (window.document.querySelector('[data-slot-proof="a"]')) fail('slot A remained after mount retarget');
  if (byId(slotHostId).data.render_slot !== 'slot:authority:a') fail('legacy render_slot declaration changed during retarget');
  window.ahSetUiNodeParam(mountNodeId, 'gate_policy', 'deny');
  await waitFor(() => !window.document.querySelector('[data-slot-proof="b"]'), 'render-slot deny gate removal');
  window.ahSetUiNodeParam(mountNodeId, 'gate_policy', 'allow-if-slot-and-host-exist');
  graph.wires = graph.wires.filter(wire => wire && wire.id !== mountWire.id);
  window.dispatchEvent(new window.CustomEvent('lm-graph-bump'));
  await waitFor(() => window.document.querySelector('[data-slot-proof="b"]'), 'render slot survives projection deletion');
  window.__uiChildHooks.recordGraphOperationNode(graph, 'node.delete', { target_ids:[mountNodeId] }, { wireTargets:false });
  graph.nodes = graph.nodes.filter(node => node && node.id !== mountNodeId);
  window.dispatchEvent(new window.CustomEvent('lm-graph-bump'));
  await delay(100);
  if (window.document.querySelector('[data-slot-proof="a"]') || window.document.querySelector('[data-slot-proof="b"]')) {
    fail('deleted render-slot relation node fell back to render_slot declaration');
  }

  const surfaceRefWire = graph.wires.find(wire => {
    const data = wire && wire.data && typeof wire.data === 'object' ? wire.data : {};
    return data.wire_family === 'ui_render_slot_mount' && data.role !== 'wire_endpoint' && data.target_owner === surfaceRefHostId;
  });
  const surfaceRefNodeId = surfaceRefWire && surfaceRefWire.data && surfaceRefWire.data.relation_node;
  let surfaceRefNode = byId(surfaceRefNodeId);
  if (!surfaceRefWire || !surfaceRefNode) fail('surface-ref mount relation missing', { surfaceRefWire, surfaceRefNodeId });
  surfaceRefNode = window.__uiChildHooks.ensureSelectedRelationWireFullAnatomy(surfaceRefNode);
  const surfaceRefKeys = new Set((surfaceRefNode.params || []).map(param => param && param.k));
  for (const key of ['render_slot', 'gate_policy', 'behavior', 'presentation']) {
    if (!surfaceRefKeys.has(key)) fail('surface-ref inspector parameter missing', { key, keys:Array.from(surfaceRefKeys) });
  }
  window.ahSetUiNodeParam(surfaceRefNodeId, 'render_slot', 'slot:surface-ref:authority-surface-b');
  await waitFor(() => window.document.querySelector('[data-surface-ref-proof="b"]'), 'retargeted surface-ref B render');
  if (window.document.querySelector('[data-surface-ref-proof="a"]')) fail('surface-ref A remained after mount retarget');
  if (byId(surfaceRefHostId).data.surface_ref !== 'authority-surface-a') fail('legacy surface_ref declaration changed during retarget');
  window.ahSetUiNodeParam(surfaceRefNodeId, 'gate_policy', 'deny');
  await waitFor(() => !window.document.querySelector('[data-surface-ref-proof="b"]'), 'surface-ref deny gate removal');
  window.ahSetUiNodeParam(surfaceRefNodeId, 'gate_policy', 'allow-if-slot-and-host-exist');
  graph.wires = graph.wires.filter(wire => wire && wire.id !== surfaceRefWire.id);
  window.dispatchEvent(new window.CustomEvent('lm-graph-bump'));
  await waitFor(() => window.document.querySelector('[data-surface-ref-proof="b"]'), 'surface ref survives projection deletion');
  window.__uiChildHooks.recordGraphOperationNode(graph, 'node.delete', { target_ids:[surfaceRefNodeId] }, { wireTargets:false });
  graph.nodes = graph.nodes.filter(node => node && node.id !== surfaceRefNodeId);
  window.dispatchEvent(new window.CustomEvent('lm-graph-bump'));
  await delay(100);
  if (window.document.querySelector('[data-surface-ref-proof="a"]') || window.document.querySelector('[data-surface-ref-proof="b"]')) {
    fail('deleted surface-ref relation node fell back to surface_ref declaration');
  }

  const bindingWire = graph.wires.find(wire => {
    const data = wire && wire.data && typeof wire.data === 'object' ? wire.data : {};
    return data.role === 'relation' && data.wire_family === 'ui_binding' && data.target_node === bindingTargetId;
  });
  const bindingNodeId = bindingWire && bindingWire.data && bindingWire.data.relation_node;
  let bindingNode = byId(bindingNodeId);
  if (!bindingWire || !bindingNode) fail('canonical binding relation missing', { bindingWire, bindingNodeId });
  const legacyProjection = graph.wires.find(wire => wire && wire.id === 'w:legacy-binding-projection');
  if (!legacyProjection || legacyProjection.data.role !== 'ui_binding_projection') {
    fail('legacy binding edge was not demoted to a projection', { legacyProjection });
  }
  bindingNode = window.__uiChildHooks.ensureSelectedRelationWireFullAnatomy(bindingNode);
  const bindingKeys = new Set((bindingNode.params || []).map(param => param && param.k));
  for (const key of ['source_node', 'binding_key', 'gate_policy', 'behavior', 'presentation']) {
    if (!bindingKeys.has(key)) fail('binding inspector parameter missing', { key, keys:Array.from(bindingKeys) });
  }
  window.ahSetUiNodeParam(bindingNodeId, 'source_node', bindingSourceBId);
  await waitFor(() => {
    const el = window.document.querySelector('[data-node="' + bindingTargetId + '"]');
    return el && el.textContent === 'BINDING_B';
  }, 'binding source B retarget');
  if (byId(bindingTargetId).data.bind !== bindingSourceAId) fail('legacy bind declaration changed during relation retarget');
  window.ahSetUiNodeParam(bindingNodeId, 'gate_policy', 'deny');
  await waitFor(() => {
    const el = window.document.querySelector('[data-node="' + bindingTargetId + '"]');
    return el && el.textContent === '';
  }, 'binding deny gate');
  window.ahSetUiNodeParam(bindingNodeId, 'gate_policy', 'allow-if-source-and-target-exist');
  graph.wires = graph.wires.filter(wire => wire && wire.id !== bindingWire.id);
  window.dispatchEvent(new window.CustomEvent('lm-graph-bump'));
  await waitFor(() => {
    const el = window.document.querySelector('[data-node="' + bindingTargetId + '"]');
    return el && el.textContent === 'BINDING_B';
  }, 'binding survives projection deletion');
  window.__uiChildHooks.recordGraphOperationNode(graph, 'node.delete', { target_ids:[bindingNodeId] }, { wireTargets:false });
  graph.nodes = graph.nodes.filter(node => node && node.id !== bindingNodeId);
  window.dispatchEvent(new window.CustomEvent('lm-graph-bump'));
  await delay(100);
  const bindingAfterDelete = window.document.querySelector('[data-node="' + bindingTargetId + '"]');
  if (bindingAfterDelete && bindingAfterDelete.textContent !== '') {
    fail('deleted binding relation node fell back to bind declaration or legacy projection', {
      text:bindingAfterDelete.textContent,
      legacyProjection,
    });
  }

  console.log('VERIFY_UI_CHILD_RELATION_AUTHORITY ' + JSON.stringify({
    ok:true,
    relationWire:relationWire.id,
    relationNode:relationNodeId,
    endpointWireCount:endpoints.length,
    inspectorParams:Array.from(keys).sort(),
    compatibilityChildren:byId(parentId).data.children,
    retargetedTo:childBId,
    denyGateRemovedChild:true,
    projectionDeletionPreservedBehavior:true,
    relationNodeDeletionDidNotFallback:true,
    renderSlotAuthority:{
      relationWire:mountWire.id,
      relationNode:mountNodeId,
      endpointWireCount:mountEndpoints.length,
      compatibilityDeclaration:byId(slotHostId).data.render_slot,
      retargetedTo:'slot:authority:b',
      denyGateRemovedSlot:true,
      projectionDeletionPreservedBehavior:true,
      relationNodeDeletionDidNotFallback:true,
    },
    surfaceRefAuthority:{
      relationWire:surfaceRefWire.id,
      relationNode:surfaceRefNodeId,
      compatibilityDeclaration:byId(surfaceRefHostId).data.surface_ref,
      retargetedTo:'slot:surface-ref:authority-surface-b',
      denyGateRemovedSurface:true,
      projectionDeletionPreservedBehavior:true,
      relationNodeDeletionDidNotFallback:true,
    },
    bindingAuthority:{
      relationWire:bindingWire.id,
      relationNode:bindingNodeId,
      compatibilityDeclaration:byId(bindingTargetId).data.bind,
      legacyProjectionRole:legacyProjection.data.role,
      retargetedTo:bindingSourceBId,
      denyGateRemovedValue:true,
      projectionDeletionPreservedBehavior:true,
      relationNodeDeletionDidNotFallback:true,
    },
  }, null, 2));
  clearTimeout(SELF_TIMEOUT);
  process.exit(0);
}

main().catch(error => fail('unexpected verifier error', {
  message:error && error.message || String(error),
  stack:error && error.stack || '',
}));
