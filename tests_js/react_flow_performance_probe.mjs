import { JSDOM } from 'jsdom';
import React from 'react';
import { createRoot } from 'react-dom/client';
import { performance } from 'node:perf_hooks';


const dom = new JSDOM('<!doctype html><div id="root"></div>', {
  url: 'http://127.0.0.1:8501/',
  pretendToBeVisual: true,
});
const { window } = dom;
Object.assign(globalThis, {
  window,
  document: window.document,
  HTMLElement: window.HTMLElement,
  SVGElement: window.SVGElement,
  Element: window.Element,
  Node: window.Node,
  ResizeObserver: class ResizeObserver {
    constructor(callback) { this.callback = callback; }
    observe(target) {
      window.setTimeout(() => this.callback([{
        target,
        contentRect: target.getBoundingClientRect(),
      }]), 0);
    }
    unobserve() {}
    disconnect() {}
  },
  DOMMatrixReadOnly: class DOMMatrixReadOnly {
    constructor() {
      this.m22 = 1;
    }
  },
});
window.ResizeObserver = globalThis.ResizeObserver;
window.DOMMatrixReadOnly = globalThis.DOMMatrixReadOnly;
window.requestAnimationFrame = callback => window.setTimeout(
  () => callback(window.performance.now()), 0);
window.cancelAnimationFrame = handle => window.clearTimeout(handle);
globalThis.requestAnimationFrame = window.requestAnimationFrame;
globalThis.cancelAnimationFrame = window.cancelAnimationFrame;
window.SVGElement.prototype.getBBox = () => ({
  x: 0, y: 0, width: 0, height: 0,
});
Object.defineProperties(window.HTMLElement.prototype, {
  offsetHeight: { get() { return parseFloat(this.style.height) || 134; } },
  offsetWidth: { get() { return parseFloat(this.style.width) || 204; } },
});

const moduleStarted = performance.now();
const { ReactFlow } = await import('@xyflow/react');
const moduleImportMs = performance.now() - moduleStarted;

const nodeCount = 250;
const edgeCount = 500;
const nodes = Array.from({length: nodeCount}, (_, index) => ({
  id: `court:node:${index}`,
  position: {
    x: 60 + (index % 25) * 244,
    y: 92 + Math.floor(index / 25) * 174,
  },
  data: {label: `Court node ${index + 1}`},
  width: 204,
  height: 134,
  selected: index === 0,
}));
const edges = Array.from({length: edgeCount}, (_, index) => ({
  id: `court:relation:${index}`,
  source: `court:node:${index % nodeCount}`,
  target: `court:node:${(index * 7 + 1) % nodeCount}`,
  selected: false,
}));

const host = document.getElementById('root');
host.style.width = '1200px';
host.style.height = '800px';
host.getBoundingClientRect = () => ({
  x: 0, y: 0, left: 0, top: 0, right: 1200, bottom: 800,
  width: 1200, height: 800, toJSON() { return this; },
});
const root = createRoot(host);

function flow(currentNodes) {
  return React.createElement(ReactFlow, {
    nodes: currentNodes,
    edges,
    defaultViewport: {x: 0, y: 0, zoom: 1},
    onlyRenderVisibleElements: false,
    nodesDraggable: false,
    panOnDrag: false,
    elementsSelectable: true,
    minZoom: 0.25,
    maxZoom: 2.5,
  });
}

async function waitUntil(predicate, timeoutMs = 5000) {
  const started = performance.now();
  while (!predicate()) {
    if (performance.now() - started > timeoutMs) {
      throw new Error(
        `React Flow rendered-DOM condition timed out: nodes=${
          host.querySelectorAll('.react-flow__node').length
        } edges=${host.querySelectorAll('.react-flow__edge').length}`
      );
    }
    await new Promise(resolve => window.setTimeout(resolve, 1));
  }
}

const initialStarted = performance.now();
root.render(flow(nodes));
await waitUntil(() => (
  host.querySelectorAll('.react-flow__node').length === nodeCount
  && host.querySelectorAll('.react-flow__edge').length === edgeCount
));
const initialRenderMs = performance.now() - initialStarted;

const selectedNodes = nodes.map((node, index) => {
  if (index !== 0 && index !== nodeCount - 1) return node;
  return {...node, selected: index === nodeCount - 1};
});
const reconcileStarted = performance.now();
root.render(flow(selectedNodes));
await waitUntil(() => (
  host.querySelector('.react-flow__node[data-id="court:node:249"].selected')
  && host.querySelectorAll('.react-flow__edge').length === edgeCount
));
const selectionReconcileMs = performance.now() - reconcileStarted;

process.stdout.write(JSON.stringify({
  nodeCount: host.querySelectorAll('.react-flow__node').length,
  edgeCount: host.querySelectorAll('.react-flow__edge').length,
  selectedId: host.querySelector('.react-flow__node.selected')?.dataset.id || null,
  moduleImportMs,
  initialRenderMs,
  selectionReconcileMs,
}));
root.unmount();
await new Promise(resolve => window.setTimeout(resolve, 0));
dom.window.close();
