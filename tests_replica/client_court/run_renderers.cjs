// Runs the REAL client source against a REAL projection and reports one
// verdict PER RENDERER. Stopping at the first failure would let a single
// fix turn four unmet contracts green -- the drift mechanism reproducing
// itself inside its own guard.
const fs = require('fs');
require('./dom_shim.cjs');

const clientSource = fs.readFileSync(process.argv[2], 'utf8');
const projection = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));

const RENDERERS = [
  'renderStaticControls', 'renderLibrary', 'renderCanvas',
  'renderInspector', 'renderToolbar',
];

// The client is an IIFE that closes over its renderers and calls refresh()
// on load. Neutralise only the network and the entry call, then export the
// real closure -- never reimplement what it demands.
let harnessed = clientSource.replace(/\n\s*refresh\(\);\n/, '\n');
harnessed = harnessed.replace(
  '(() => {',
  '(() => {\n  globalThis.__exportRenderers = () => ({' +
  RENDERERS.map(name => `${name}: typeof ${name} === 'function' ? ${name} : null`).join(', ') +
  '});',
);

const verdicts = {};
try {
  new Function(harnessed)();
} catch (error) {
  console.log(JSON.stringify({
    loaded: false, error: String(error && error.message || error), verdicts,
  }));
  process.exit(0);
}

const renderers = globalThis.__exportRenderers ? globalThis.__exportRenderers() : {};
for (const name of RENDERERS) {
  const fn = renderers[name];
  if (typeof fn !== 'function') {
    verdicts[name] = { ok: false, error: 'renderer not found in client source' };
    continue;
  }
  try {
    fn(projection);
    verdicts[name] = { ok: true };
  } catch (error) {
    verdicts[name] = { ok: false, error: String(error && error.message || error) };
  }
}
// A shim is dishonest in two directions and a court that checks one while
// claiming both is worse than one that checks neither, because it reads as
// covered. First direction: it must not INVENT what the browser lacks.
// Second: it must REFUSE what the browser refuses -- a shim that quietly
// accepts an undefined child turns "the catalogue entry was missing, so
// the element was never built" into a pass, which is the gap this court
// exists to find hiding inside the court itself.
function refuses(operation) {
  try {
    operation();
    return false;
  } catch (error) {
    return error instanceof TypeError;
  }
}
const probe = document.createElement('div');
const child = document.createElement('span');
probe.append(child);
const orphan = document.createElement('em');
const prependProbe = document.createElement('div');
prependProbe.append(document.createElement('i'));
prependProbe.prepend(document.createElement('b'));
const shimChecks = {
  invents_nothing: document.querySelector('.not-a-served-selector') === null,
  refuses_undefined_child: refuses(() => probe.appendChild(undefined)),
  refuses_non_node: refuses(() => probe.append('text')),
  refuses_foreign_reference: refuses(
    () => probe.insertBefore(document.createElement('p'), orphan),
  ),
  children_and_childnodes_agree:
    prependProbe.children.length === prependProbe.childNodes.length
    && prependProbe.children.every((node, at) => node === prependProbe.childNodes[at]),
  remove_detaches: (() => {
    const parent = document.createElement('div');
    const leaving = document.createElement('span');
    parent.append(leaving);
    leaving.remove();
    return parent.children.length === 0 && parent.childNodes.length === 0;
  })(),
};
const shimHonest = Object.values(shimChecks).every(Boolean);
console.log(JSON.stringify({
  loaded: true, shim_honest: shimHonest, shim_checks: shimChecks, verdicts,
}));
