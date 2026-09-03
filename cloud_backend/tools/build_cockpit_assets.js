// Precompiles the cockpit's JSX with the same @babel/standalone the page used to
// load in the browser. Run after editing any cockpit_assets/*.jsx:
//     node cloud_backend/tools/build_cockpit_assets.js
// map.html loads compiled/*.js; the browser no longer downloads 3.1 MB of Babel and
// transpiles 300 KB of JSX on every open.
const fs = require('fs'), path = require('path');
const root = path.resolve(__dirname, '..', 'cockpit_assets');
const Babel = require(path.join(root, 'vendor', 'babel.js'));
const order = ['tokens', 'cockpit-core', 'hub-kit', 'atlas-engine', 'atlas-runtime', 'atlas-panels', 'atlas-side', 'atlas-cockpit'];
fs.mkdirSync(path.join(root, 'compiled'), { recursive: true });
for (const name of order) {
  const src = fs.readFileSync(path.join(root, name + '.jsx'), 'utf8');
  const out = Babel.transform(src, { presets: ['env', 'react'], sourceType: 'script', filename: name + '.jsx', compact: false }).code;
  fs.writeFileSync(path.join(root, 'compiled', name + '.js'), out + '\n');
  console.log(name.padEnd(14), String(src.length).padStart(6), '->', String(out.length).padStart(6));
}
