/* Read-only baseline attribution: substitute only changed Studio files in memory.
 * No checkout, extraction, installed app, provider or second Studio build.
 * Run with node --require ./tests_js/social3_baseline_hook.cjs --test ...
 */
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {execFileSync} = require('node:child_process');
const {createHash} = require('node:crypto');
const root = path.resolve(__dirname, '..');
const original = fs.readFileSync.bind(fs);
const revision = 'e41d56aaa1bd23fd154b4b1ccc90ad0430dcebe3';
const replacements = new Map();
const hashes = new Map();
let Babel;
for (const name of ['studio-lm.jsx','studio-params.jsx','studio-existing-workshop.js']) {
  const relative = 'nodelang/studio/' + name;
  const source = execFileSync('git',['show',revision + ':' + relative],{cwd:root,maxBuffer:4*1024*1024}).toString('utf8');
  replacements.set(path.join(root,relative),source);
  if (!name.endsWith('.jsx')) continue;
  if (!Babel) {
    const exports = {};
    vm.runInNewContext(original(path.join(root,'nodelang/studio/vendor/babel.js'),'utf8'),{exports,module:{exports}});
    Babel = exports;
  }
  hashes.set(name,createHash('sha256').update(source).digest('hex'));
  const compiled = Babel.transform(source,{presets:['react','env'],plugins:[
    'transform-class-properties','transform-object-rest-spread','transform-flow-strip-types'],targets:{},sourceMaps:false}).code;
  replacements.set(path.join(root,'nodelang/studio/compiled',name.replace('.jsx','.js')),compiled);
}
const manifestPath = path.join(root,'nodelang/studio/compiled/manifest.json');
const manifest = JSON.parse(original(manifestPath,'utf8'));
for (const file of manifest.files) if (hashes.has(file.source)) file.source_sha256 = hashes.get(file.source);
replacements.set(manifestPath,JSON.stringify(manifest));
fs.readFileSync = function(filename,options) {
  const name = typeof filename === 'string' ? path.resolve(filename) : '';
  if (!replacements.has(name)) return original(filename,options);
  const encoding = typeof options === 'string' ? options : options?.encoding;
  const data = Buffer.from(replacements.get(name),'utf8');
  return encoding ? data.toString(encoding) : data;
};
