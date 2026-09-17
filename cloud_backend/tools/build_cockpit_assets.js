// Compiles the founder cockpit FROM its one source, 13.NODE-LANGUAGE/nodelang/studio, with the same
// @babel/standalone the page used to load in the browser. The .jsx modules live only there (founder,
// 2026-09-17: one source for everything); this tree keeps map.html, the vendor files and the compiled
// output. Run after editing any cockpit module:
//     node cloud_backend/tools/build_cockpit_assets.js
// ARCHHUB_STUDIO_SOURCES points at the studio tree when it is not beside this checkout.
// compiled/manifest.json records the source bytes each bundle was built from, so a court can tell a
// stale bundle from a fresh one without trusting file times.
const fs = require('fs'), path = require('path'), crypto = require('crypto');
const assets = path.resolve(__dirname, '..', 'cockpit_assets');
const studio = path.resolve(process.env.ARCHHUB_STUDIO_SOURCES ||
  path.join(__dirname, '..', '..', '..', '13.NODE-LANGUAGE', 'nodelang', 'studio'));
const Babel = require(path.join(assets, 'vendor', 'babel.js'));
const order = ['tokens', 'param-types', 'cockpit-core', 'hub-kit', 'atlas-engine', 'atlas-runtime', 'atlas-panels', 'atlas-side', 'atlas-cockpit'];
const sha = (bytes) => crypto.createHash('sha256').update(bytes).digest('hex');
const missing = order.filter(name => !fs.existsSync(path.join(studio, name + '.jsx')));
if (missing.length) {
  console.error('The cockpit source is not at ' + studio + ' (missing ' + missing.join(', ') + '). Set ARCHHUB_STUDIO_SOURCES.');
  process.exit(1);
}
fs.mkdirSync(path.join(assets, 'compiled'), { recursive: true });
const files = [];
for (const name of order) {
  const bytes = fs.readFileSync(path.join(studio, name + '.jsx'));
  const out = Babel.transform(bytes.toString('utf8'), { presets: ['env', 'react'], sourceType: 'script', filename: name + '.jsx', compact: false }).code + '\n';
  fs.writeFileSync(path.join(assets, 'compiled', name + '.js'), out);
  files.push({ module: name, source: name + '.jsx', source_sha256: sha(bytes), output: name + '.js', output_sha256: sha(Buffer.from(out, 'utf8')) });
  console.log(name.padEnd(14), String(bytes.length).padStart(6), '->', String(out.length).padStart(6));
}
fs.writeFileSync(path.join(assets, 'compiled', 'manifest.json'),
  JSON.stringify({ source_root: '13.NODE-LANGUAGE/nodelang/studio', files }, null, 1) + '\n');