// Minimal DOM shim: EXACTLY the skeleton the server serves, nothing more.
// A permissive shim that invents elements turns real failures into passes
// and makes the court vacuous, so anything the client reaches for beyond
// the served skeleton must fail here as it would in a browser.
const SERVED = new Set([
  '.canvas', '.canvas-stage', '.inspector', '.sidebar', '.library-panel',
  '.sidebar > .library-panel', '.canvas-toolbar', '.icon-rail', 'body',
  'html', 'head',
]);

function requireNode(candidate, operation) {
  // The browser throws TypeError when handed a non-node. So does this.
  if (
    candidate === null || candidate === undefined
    || typeof candidate !== 'object' || typeof candidate.tagName !== 'string'
  ) {
    throw new TypeError(
      operation + ': argument is not a node (' + String(candidate) + ')',
    );
  }
  return candidate;
}

function makeElement(tag = 'div', selector = null) {
  const node = {
    tagName: String(tag).toUpperCase(),
    selector,
    className: '',
    id: '',
    textContent: '',
    innerHTML: '',
    title: '',
    draggable: false,
    hidden: false,
    parentNode: null,
    children: [],
    childNodes: [],
    dataset: {},
    style: { setProperty() {}, removeProperty() {}, getPropertyValue: () => '' },
    classList: {
      _v: new Set(),
      add(...n) { n.forEach(x => this._v.add(x)); },
      remove(...n) { n.forEach(x => this._v.delete(x)); },
      toggle(n) { this._v.has(n) ? this._v.delete(n) : this._v.add(n); },
      contains(n) { return this._v.has(n); },
    },
    attributes: {},
    setAttribute(name, value) {
      this.attributes[name] = String(value);
      if (name.startsWith('data-')) {
        this.dataset[name.slice(5).replace(/-([a-z])/g, (_m, c) => c.toUpperCase())] =
          String(value);
      }
    },
    getAttribute(name) {
      return Object.prototype.hasOwnProperty.call(this.attributes, name)
        ? this.attributes[name] : null;
    },
    removeAttribute(name) { delete this.attributes[name]; },
    hasAttribute(name) {
      return Object.prototype.hasOwnProperty.call(this.attributes, name);
    },
    // A shim is dishonest in TWO directions: hallucinating what the browser
    // lacks, and ACCEPTING WHAT THE BROWSER REJECTS. The second turns a
    // renderer that appended an undefined element -- because the catalogue
    // entry it needed was missing -- into a passing verdict, which is the
    // very gap the contract court exists to find, hiding inside the court.
    append(...kids) {
      kids.forEach(kid => {
        requireNode(kid, 'append');
        kid.parentNode = this;
        this.children.push(kid);
        this.childNodes.push(kid);
      });
    },
    appendChild(kid) { this.append(kid); return kid; },
    prepend(...kids) {
      kids.forEach(kid => requireNode(kid, 'prepend'));
      kids.forEach(kid => { kid.parentNode = this; });
      // children and childNodes are one tree seen twice. Updating only one
      // makes the verdict depend on which array a renderer happens to read.
      this.children.unshift(...kids);
      this.childNodes.unshift(...kids);
    },
    replaceChildren(...kids) {
      kids.forEach(kid => requireNode(kid, 'replaceChildren'));
      this.children.forEach(kid => { kid.parentNode = null; });
      kids.forEach(kid => { kid.parentNode = this; });
      this.children = [...kids];
      this.childNodes = [...kids];
    },
    insertBefore(kid, reference) {
      requireNode(kid, 'insertBefore');
      if (reference === null || reference === undefined) {
        this.append(kid);
        return kid;
      }
      const at = this.children.indexOf(reference);
      if (at < 0) {
        throw new TypeError(
          'insertBefore: the reference node is not a child of this node',
        );
      }
      kid.parentNode = this;
      this.children.splice(at, 0, kid);
      this.childNodes.splice(at, 0, kid);
      return kid;
    },
    remove() {
      const parent = this.parentNode;
      if (!parent) return;
      [parent.children, parent.childNodes].forEach(list => {
        const at = list.indexOf(this);
        if (at >= 0) list.splice(at, 1);
      });
      this.parentNode = null;
    },
    addEventListener() {},
    removeEventListener() {},
    closest() { return null; },
    contains() { return false; },
    getBoundingClientRect() {
      return { x: 0, y: 0, top: 0, left: 0, right: 0, bottom: 0, width: 0, height: 0 };
    },
    focus() {},
    blur() {},
    scrollIntoView() {},
    // Descendant lookups search only what was actually appended -- never
    // invent. Returning null is how the browser reports a missing node and
    // is what makes a missing contract observable rather than papered over.
    querySelector(sel) { return findIn(this, sel); },
    querySelectorAll(sel) { return collectIn(this, sel); },
  };
  return node;
}

function matches(node, sel) {
  if (!sel) return false;
  const attr = sel.match(/^\[([^\]=]+)(?:=["']?([^"'\]]*)["']?)?\]$/);
  if (attr) {
    const [, name, value] = attr;
    // A browser keeps dataset and attributes as one view of the same
    // thing: setAttribute('data-x') is readable as dataset.x and the
    // reverse. The client sets descriptor attributes with setAttribute and
    // reads its own markers back through dataset, so a shim that honours
    // only one of the two manufactures failures the browser never has --
    // which is the too-STRICT twin of the permissive-shim trap, and just
    // as fatal to the verdicts.
    const key = name.startsWith('data-')
      ? name.slice(5).replace(/-([a-z])/g, (_m, c) => c.toUpperCase())
      : null;
    const fromDataset = key !== null
      && Object.prototype.hasOwnProperty.call(node.dataset, key);
    const fromAttribute = node.hasAttribute(name);
    if (!fromDataset && !fromAttribute) return false;
    if (value === undefined) return true;
    const actual = fromDataset ? node.dataset[key] : node.getAttribute(name);
    return String(actual) === value;
  }
  if (sel.startsWith('.')) return node.classList.contains(sel.slice(1));
  if (sel.startsWith('#')) return node.id === sel.slice(1);
  return node.tagName === sel.toUpperCase();
}

function findIn(root, sel) {
  const last = sel.split('>').pop().trim().split(/\s+/).pop();
  for (const kid of root.children) {
    if (matches(kid, last)) return kid;
    const deeper = findIn(kid, sel);
    if (deeper) return deeper;
  }
  return null;
}

function collectIn(root, sel) {
  const last = sel.split('>').pop().trim().split(/\s+/).pop();
  const found = [];
  for (const kid of root.children) {
    if (matches(kid, last)) found.push(kid);
    found.push(...collectIn(kid, sel));
  }
  return found;
}

const body = makeElement('body', 'body');
const skeleton = {};
[['.icon-rail', 'nav'], ['.sidebar', 'aside'], ['.canvas-toolbar', 'div'],
 ['.canvas', 'div'], ['.inspector', 'aside']].forEach(([sel, tag]) => {
  const node = makeElement(tag, sel);
  node.classList.add(sel.slice(1));
  skeleton[sel] = node;
  body.append(node);
});
const libraryPanel = makeElement('div', '.library-panel');
libraryPanel.classList.add('library-panel');
skeleton['.library-panel'] = libraryPanel;
skeleton['.sidebar'].append(libraryPanel);
const stage = makeElement('div', '.canvas-stage');
stage.classList.add('canvas-stage');
skeleton['.canvas-stage'] = stage;
skeleton['.canvas'].append(stage);

const meta = makeElement('meta', 'meta');
meta.content = 'court-csrf';

globalThis.document = {
  body,
  documentElement: makeElement('html', 'html'),
  head: makeElement('head', 'head'),
  createElement: tag => makeElement(tag),
  createElementNS: (_ns, tag) => makeElement(tag),
  createTextNode: text => ({ textContent: text }),
  addEventListener() {},
  removeEventListener() {},
  querySelector(sel) {
    if (sel.includes('archhub-csrf')) return meta;
    if (Object.prototype.hasOwnProperty.call(skeleton, sel)) return skeleton[sel];
    const trimmed = sel.split('>').pop().trim();
    if (Object.prototype.hasOwnProperty.call(skeleton, trimmed)) return skeleton[trimmed];
    return findIn(body, sel);
  },
  querySelectorAll(sel) { return collectIn(body, sel); },
  getElementById() { return null; },
};
globalThis.window = {
  addEventListener() {}, removeEventListener() {},
  requestAnimationFrame(fn) { return 0; },
  cancelAnimationFrame() {},
  getComputedStyle: () => ({ getPropertyValue: () => '' }),
  matchMedia: () => ({ matches: false, addEventListener() {} }),
  location: { origin: 'http://127.0.0.1', href: 'http://127.0.0.1/' },
  __archhubSession: { token: 'court', csrf: 'court-csrf' },
};
globalThis.requestAnimationFrame = globalThis.window.requestAnimationFrame;
globalThis.cancelAnimationFrame = () => {};
globalThis.getComputedStyle = globalThis.window.getComputedStyle;
globalThis.navigator = { userAgent: 'archhub-court' };
globalThis.SERVED_SELECTORS = SERVED;
globalThis.__skeleton = skeleton;
