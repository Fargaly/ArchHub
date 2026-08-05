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
// C7: prove the shim is not permissive. A selector the server never serves
// must be null, or every verdict above is worthless.
const shimHonest = document.querySelector('.not-a-served-selector') === null;
console.log(JSON.stringify({ loaded: true, shim_honest: shimHonest, verdicts }));
