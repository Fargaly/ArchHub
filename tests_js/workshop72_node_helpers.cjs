const fs = require('node:fs');
const path = require('node:path');
const vm = require('./studio_ds_context.cjs');
const assert = require('node:assert/strict');
const studioRoot = path.resolve(__dirname, '..');
const read = file => fs.readFileSync(path.join(studioRoot, file), 'utf8');
const studio = () => read('nodelang/studio/studio-lm.jsx');
function slice(source, start, end) {
  const a = source.indexOf(start), b = source.indexOf(end, a + start.length);
  assert.ok(a >= 0 && b > a, start + ' is read from the shipped source');
  return source.slice(a, b);
}
const nodePreviewSource = source => slice(source,'const watchPreviewFor =','const WATCH_TABLE_ROWS =') +
  slice(source,'const nodePlanPreviewFor =','const NodeBody =');
async function mountWorkshopNode({state, node, libraryMode = false, onMemberLeave, screenToCanvasPoint, onSocket, onSocketDrag, onOpen, onFocus} = {}) {
  const {JSDOM} = await import('jsdom');
  const dom = new JSDOM('<div id="root"></div>', {url:'http://127.0.0.1/', pretendToBeVisual:true});
  const win = dom.window, previous = {window:global.window, document:global.document};
  global.window = win; global.document = win.document; global.IS_REACT_ACT_ENVIRONMENT = true;
  const React = require('react'), {createRoot} = require('react-dom/client'), {transformSync} = require('esbuild');
  let snapshot = state;
  const listeners = new Set(), calls = [], navigation = [];
  win.ARCHHUB_EXISTING_WORKSHOP = {getSnapshot:() => snapshot, subscribe:fn => {listeners.add(fn); return () => listeners.delete(fn);},
    openWorkshop:async (...args) => calls.push(['openWorkshop', ...args]),
    sendModelConversation:async (...args) => calls.push(['sendModelConversation', ...args]),
    moveMember:async (...args) => calls.push(['moveMember', ...args])};
  win.addEventListener('archhub:reach-conversation', event => navigation.push(event.detail));
  const context = vm.createContext({React, window:win, document:win.document, console, setTimeout, clearTimeout});
  vm.runInContext(read('nodelang/studio/tokens.jsx'), context);
  vm.runInContext(slice(read('nodelang/studio/shared-data.jsx'), 'window.ARCHHUB_WORKSHOP_TASK_SOURCE =', 'const HOSTS ='), context);
  const source = studio();
  const hooks = slice(source, 'const useWorkshopProjection =', 'const studioCanvasScope =');
  const constants = slice(source, 'const SOCKET_TOP =', 'const nodeCardTitle =');
  const renderer = slice(source, 'const NodeRenderer =', '// A card re-renders only when what it draws changed');
  const face = slice(source, 'const isWorkshopGraphNode =', 'const NodeBody =');
  const socket = slice(source, 'const Socket =', '// \u2500\u2500\u2500 per-category body content');
  Object.assign(context, {LM:win.AH, WIRE:{}, studioCategory:() => ({col:win.AH.purple}),
    nodeCardTitle:n => n.title || 'Workshop', nodeCardSubtitle:() => '',
    isSessionNodeShape:() => false, NodeBody:() => null,
    socketTypeLabel:t => t, socketShapeOf:(t,list) => list ? 'diamond' : t === 'trigger' ? 'triangle' : 'circle'});
  win.ApplicationNodeParameters=({status}) => status || null; // Isolated NodeBody dependency; full owner/write courts mount Studio.
  const previewSource = slice(source,'const nodeIsWatch =','const visibleNodeParams =') +
    slice(source,'const watchPreviewFor =','const WATCH_TABLE_ROWS =');
  vm.runInContext(transformSync(hooks + constants + previewSource + renderer + socket + face + '\nglobalThis.NodeRenderer = NodeRenderer;', {loader:'jsx'}).code, context);
  const container = win.document.getElementById('root'), root = createRoot(container);
  const act = fn => React.act(async () => {await fn();});
  let heldNode = node;
  const props = () => ({n:heldNode, libraryMode, onPortBand:() => {}, onSocket:onSocket || ((...args) => calls.push(['socket',...args])),
    onSocketDrag, onMemberLeave:onMemberLeave || ((...args) => calls.push(['memberLeave',...args])),
    screenToCanvasPoint:screenToCanvasPoint || ((x,y) => ({x,y})),
    onDragStart:() => calls.push(['dragStart']), onFocus:onFocus || (() => {}), onOpen, selected:false, focused:false});
  const draw = async next => {
    if (next) {
      if (next.state) snapshot = next.state;
      if (next.node) heldNode = next.node;
    }
    await act(() => {for (const fn of listeners) fn(); root.render(React.createElement(context.NodeRenderer, props()));});
    return win.document;
  };
  await draw();
  return {win, doc:win.document, container, context, calls, navigation, draw, render:draw, act,
    state:() => snapshot, model:() => win.ARCHHUB_WORKSHOP_MODEL({state:snapshot, descriptor:snapshot.workshops[0]}),
    click:el => act(() => el.dispatchEvent(new win.MouseEvent('click', {bubbles:true}))),
    mouse:(el,type,x,y) => act(() => el.dispatchEvent(new win.MouseEvent(type,{bubbles:true,clientX:x,clientY:y,button:0}))),
    close:async () => {await act(() => root.unmount()); win.close(); global.window=previous.window; global.document=previous.document;
      delete global.IS_REACT_ACT_ENVIRONMENT;}};
}
module.exports = {mountWorkshopNode, mountNode:mountWorkshopNode, slice, read, nodePreviewSource};
