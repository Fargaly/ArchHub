const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('./studio_ds_context.cjs');
const source = fs.readFileSync(path.join(__dirname, '../nodelang/studio/studio-lm.jsx'), 'utf8');
const part = (start, end) => source.slice(source.indexOf(start), source.indexOf(end, source.indexOf(start)));

async function mount() {
  const {JSDOM} = await import('jsdom');
  const React = require('react'), {createRoot} = require('react-dom/client'), {transformSync} = require('esbuild');
  const dom = new JSDOM('<div id="root"></div>', {url:'http://127.0.0.1/'}), win = dom.window;
  const previous = {window:global.window, document:global.document};
  global.window = win; global.document = win.document; global.IS_REACT_ACT_ENVIRONMENT = true;
  // jsdom has no layout: use the rendered width, and a measured tall body rather than the stale graph h.
  Object.defineProperty(win.HTMLElement.prototype, 'offsetWidth', {configurable:true, get() {return parseFloat(this.style.width) || 224;}});
  Object.defineProperty(win.HTMLElement.prototype, 'offsetHeight', {configurable:true, get() {return 310;}});
  win.HTMLElement.prototype.getBoundingClientRect = function() {
    const left = parseFloat(this.style.left) || 0, top = parseFloat(this.style.top) || 0;
    const width = this.classList.contains('lm-node') ? this.offsetWidth : 1200, height = this.classList.contains('lm-node') ? this.offsetHeight : 800;
    return {left, top, width, height, right:left + width, bottom:top + height};
  };
  const base = {cat:'logic', live:true, engine:'lines.watch', sub:'lines.watch', w:210, h:80,
    params:[{k:'seed', v:'skip'}, {k:'interval', v:'60'}], ins:[], outs:[], group:'', application:false};
  let snapshot = {graph:{nodes:[{...base, id:'source', title:'Line Watcher', x:100, y:100},
    {...base, id:'neighbor', title:'Neighbor', x:364, y:100}], wires:[]},
    canvas:{revision:1, scope:{current:'scope'}, authorization:{subject:'founder', session:'s'}}};
  const creates = [];
  win.ARCHHUB_NODE_CREATE = async spec => {
    creates.push(JSON.parse(JSON.stringify(spec)));
    const node = {...base, ...spec, id:'copy-' + creates.length, params:base.params};
    snapshot = {...snapshot, graph:{...snapshot.graph, nodes:[...snapshot.graph.nodes, node]}};
    return {ok:true, id:node.id};
  };
  win.ARCHHUB_EXISTING_WORKSHOP = {getSnapshot:() => ({topology:snapshot}), refreshTopologyCanvas:async () => snapshot};
  const context = vm.createContext({React, window:win, document:win.document, useStudioProjection:() => snapshot,
    LM_GRAPH:{nodes:[], wires:[]}, studioCanvasScope:() => 'scope', WIRE:{}, NodeBody:() => null,
    studioCategory:() => ({col:'#888', icon:'+', label:'Logic'}),
    CanvasToolbar:() => null, FloatingComposer:() => null, CanvasAddBox:() => null, MiniMap:() => null, Socket:() => null,
    nodeModelRow:() => null, smallBtn:() => ({}), toolBtn:() => ({}), kbd:() => ({}),
    setTimeout:win.setTimeout.bind(win), clearTimeout:win.clearTimeout.bind(win)});
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../nodelang/studio/tokens.jsx'), 'utf8'), context);
  context.LM = win.AH;
  const canvas = part('const SOCKET_TOP =', 'const NodeStateDot =') + require('./workshop72_node_helpers.cjs').nodePreviewSource(source);
  vm.runInContext(transformSync(part('const studioShortcut =', 'const studioRefreshCanvasInPlace =') +
    part('const studioRefreshCanvasInPlace =', '\nconst StudioLM =') + canvas + '\nglobalThis.NodeCanvas = NodeCanvas;', {loader:'jsx'}).code, context);
  const root = createRoot(win.document.getElementById('root'));
  const act = fn => React.act(async () => {await fn();});
  await act(() => root.render(React.createElement(context.NodeCanvas, {focusId:null, setFocusId:() => {},
    setLibraryOpen:() => {}, userNodes:[], addNodeFromLibrary:() => {}, model:null})));
  const card = id => win.document.querySelector('.lm-node[data-node-id="' + id + '"]');
  return {win, creates, card, act, source:() => snapshot.graph.nodes.find(n => n.id === 'source'),
    duplicate:async () => {
      await act(() => card('source').dispatchEvent(new win.MouseEvent('contextmenu', {bubbles:true, clientX:140, clientY:140})));
      const button = win.document.querySelector('[role="menuitem"][aria-label="Duplicate"]');
      assert.ok(button && !button.disabled, 'real node menu exposes Duplicate');
      await act(async () => {button.click(); await new Promise(resolve => win.setTimeout(resolve, 0));});
    },
    fork:async () => act(async () => {await win.__archhubDuplicateNode(snapshot.graph.nodes.find(n => n.id === 'source'));}),
    close:async () => {await act(() => root.unmount()); win.close(); global.window = previous.window; global.document = previous.document; delete global.IS_REACT_ACT_ENVIRONMENT;},
  };
}
const intersects = (a,b) => a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;
test('RELGATEFIX: Duplicate and Fork place tall measured cards clear of their source, neighbors and prior copies', async () => {
  const view = await mount();
  try {
    for (const [index, action] of [view.duplicate, view.fork].entries()) {
      await action();
      assert.equal(view.creates.length, index + 1, 'one create per founder action');
      assert.deepEqual(view.creates[index].params, {interval:'60'}, 'copy keeps parameters and omits the seed marker');
      const id = 'copy-' + (index + 1), copy = view.card(id);
      assert.ok(copy, 'confirmed copy is mounted after refresh');
      assert.equal(copy.getAttribute('data-selected'), 'true', 'confirmed copy is selected');
      const box = copy.getBoundingClientRect();
      assert.equal(box.height, 310, 'court measures the rendered body, not graph h=80');
      for (const other of view.win.document.querySelectorAll('.lm-node[data-node-id]')) {
        if (other !== copy) assert.equal(intersects(box, other.getBoundingClientRect()), false,
          id + ' overlaps ' + other.getAttribute('data-node-id'));
      }
      assert.deepEqual({x:view.source().x,y:view.source().y}, {x:100,y:100}, 'placement does not move the source');
    }
  } finally {await view.close();}
});
