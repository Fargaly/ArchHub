/* Explicit Studio precompile. No watcher, network, application, or provider. */
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {createHash, randomUUID} = require('node:crypto');

const owner = path.resolve(__dirname, '..');
const numbered = path.basename(owner) === '03.TOOLS';
const root = numbered ? path.dirname(owner) : owner;
const studio = path.join(root, numbered ? '01.APP/nodelang' : 'nodelang', 'studio');
const output = path.join(studio, 'compiled');
const names = ["tokens.jsx", "ds/index.jsx", "api.js", "icons.jsx", "ui.jsx", "answer-widgets.jsx", "ds_home2.jsx", "ds_workshop3.jsx", "ds_screens.jsx", "ds_library.jsx", "ds_colleagues.jsx", "ds_baboom.jsx", "ds_settings3.jsx", "watcher-controls.jsx", "ds_watch_edit.jsx", "ds_firstrun.jsx", "surfaces.jsx", "integration-states.jsx", "project-tools.jsx", "community-tools.jsx", "agent-states.jsx", "research-surfaces.jsx", "dependencies.jsx", "workflow-states.jsx", "decision-results.jsx", "review-states.jsx", "canvas-states.jsx", "desktop.jsx", "meetings.jsx", "social.jsx", "research.jsx", "xray.jsx", "access.jsx", "account-tools.jsx", "routing.jsx", "brain.jsx", "docs.jsx", "companion.jsx", "context-menus.jsx", "app.jsx"];
const version = '7.29.0';
// These are the actual classic-script defaults in this vendored version's
// transformScriptTags/SEe function. Only its inline source maps are omitted.
const options = {presets:['react', 'env'], plugins:['transform-class-properties',
  'transform-object-rest-spread', 'transform-flow-strip-types'], targets:{}, sourceMaps:false};
// The canvas engine is bundled here from the pinned npm package (package.json/lock: exactly 12.11.2),
// never committed as a minified copy. The upstream bytes are pinned by sha256 below.
const XYFLOW = {package:'@xyflow/react', version:'12.11.2', license:'MIT', upstream:'https://github.com/xyflow/xyflow',
  umd_sha256:'6709e2e548e4d7b87bdc651653f3c2af5bfaaf1360241ef59ab918c5dbcea7c8',
  css_sha256:'4171d20d683eae89681eb1fe7c3bf52d8d326103b28078484d26e2f370d81778'};
// The UMD imports react/jsx-runtime; the Studio's React is the classic UMD, so jsx/jsxs map onto createElement.
const XYFLOW_SHIM = 'window.jsxRuntime=window.jsxRuntime||{Fragment:React.Fragment,jsx:function(t,p,k){return React.createElement(t,'
  + 'k===undefined?p:Object.assign({},p,{key:k}));}};window.jsxRuntime.jsxs=window.jsxRuntime.jsx;\n';
const VENDOR_OUTPUTS = ['xyflow.js', 'xyflow.css'];
const digest = bytes => createHash('sha256').update(bytes).digest('hex');
const requireThat = (condition, message) => { if (!condition) throw new Error(message); };

function readFile(filename, limit) {
  const info = fs.lstatSync(filename);
  requireThat(info.isFile() && !info.isSymbolicLink() && info.size <= limit,
    'Studio input/output is not a bounded regular file: ' + path.relative(root, filename));
  const bytes = fs.readFileSync(filename);
  requireThat(bytes.length === info.size, 'Studio file changed during its read.');
  return bytes;
}
function input(relative, limit) {
  const physical = numbered && relative.startsWith('nodelang/') ? '01.APP/' + relative
    : numbered && relative.startsWith('packaging/') ? '03.TOOLS/' + relative : relative;
  const bytes = readFile(path.join(root, physical), limit);
  return {path:relative, bytes:bytes.length, sha256:digest(bytes)};
}
function inputs() {
  return {
    compiler:input('packaging/compile_studio.cjs', 128 * 1024),
    babel:input('nodelang/studio/vendor/babel.js', 4 * 1024 * 1024),
    loader:input('nodelang/studio/studio.html', 256 * 1024),
    stylesheet:input('nodelang/studio/style.css', 1024 * 1024),
    package:input('package.json', 128 * 1024),
  };
}
function sourceFiles() {
  const files = names.map(source => {
    const bytes = readFile(path.join(studio, source), 1024 * 1024);
    return {source, output:source.replace(/\//g, '-').replace(/\.jsx$/, '.js'), source_bytes:bytes.length,
      source_sha256:digest(bytes), text:new TextDecoder('utf-8', {fatal:true}).decode(bytes)};
  });
  requireThat(files.reduce((sum, file) => sum + file.source_bytes, 0) <= 2 * 1024 * 1024,
    'Studio sources exceed the reviewed 2 MiB aggregate bound.');
  return files;
}
function vendorOutputs() {
  // node_modules of this checkout, or the selected checkout a release snapshot was taken from.
  const roots = [process.env.ARCHHUB_NODE_MODULES, path.join(root, 'node_modules')].filter(Boolean);
  const home = roots.map(dir => path.join(dir, ...XYFLOW.package.split('/'))).find(dir => fs.existsSync(path.join(dir, 'package.json')));
  requireThat(home, XYFLOW.package + ' is not installed; run npm ci (package-lock pins ' + XYFLOW.version + ').');
  const pkg = JSON.parse(readFile(path.join(home, 'package.json'), 64 * 1024).toString('utf8'));
  requireThat(pkg.name === XYFLOW.package && pkg.version === XYFLOW.version && pkg.license === XYFLOW.license,
    XYFLOW.package + ' must be exactly ' + XYFLOW.version + ' (' + XYFLOW.license + ').');
  const umd = readFile(path.join(home, 'dist', 'umd', 'index.js'), 1024 * 1024), css = readFile(path.join(home, 'dist', 'base.css'), 256 * 1024);
  requireThat(digest(umd) === XYFLOW.umd_sha256 && digest(css) === XYFLOW.css_sha256, XYFLOW.package + ' bytes differ from the pinned release.');
  const header = '/*! ' + XYFLOW.package + ' ' + XYFLOW.version + ' | ' + XYFLOW.license + ' | ' + XYFLOW.upstream + ' */\n';
  return [Buffer.concat([Buffer.from(header + XYFLOW_SHIM), umd]), Buffer.concat([Buffer.from(header), css])].map((bytes, index) => ({bytes,
    record:{output:VENDOR_OUTPUTS[index], package:XYFLOW.package, version:XYFLOW.version, license:XYFLOW.license, upstream:XYFLOW.upstream,
      upstream_sha256:index ? XYFLOW.css_sha256 : XYFLOW.umd_sha256, bytes:bytes.length, sha256:digest(bytes),
      integrity:'sha256-' + createHash('sha256').update(bytes).digest('base64')}}));
}
function generatedDirectory(create) {
  if (create) fs.mkdirSync(output, {recursive:true});
  const info = fs.lstatSync(output);
  requireThat(info.isDirectory() && !info.isSymbolicLink(), 'Studio compiled output must be a real directory.');
}
function writeAtomic(name, bytes) {
  requireThat(name === 'manifest.json' || VENDOR_OUTPUTS.includes(name) || names.some(source => source.replace(/\//g, '-').replace(/\.jsx$/, '.js') === name),
    'Unexpected generated Studio filename.');
  const filename = path.join(output, name);
  const temporary = path.join(output, '.' + name + '.' + randomUUID() + '.tmp');
  try {
    fs.writeFileSync(temporary, bytes, {flag:'wx'});
    fs.renameSync(temporary, filename);
  } finally {
    // One exact owned temporary; never enumerate or recursively remove files.
    if (fs.existsSync(temporary)) fs.unlinkSync(temporary);
  }
}
function same(left, right) { return JSON.stringify(left) === JSON.stringify(right); }

function main() {
  const args = process.argv.slice(2);
  requireThat(args.length === 0 || (args.length === 1 && args[0] === '--check'),
    'Usage: node packaging/compile_studio.cjs [--check]');
  const checking = args[0] === '--check';
  const heldInputs = inputs(), sources = sourceFiles();
  const manifestPath = path.join(output, 'manifest.json');
  if (checking) {
    generatedDirectory(false);
    const manifest = JSON.parse(readFile(manifestPath, 32 * 1024).toString('utf8'));
    requireThat(manifest.format === 1 && manifest.babel_version === version && same(manifest.options, options)
      && same(manifest.inputs, heldInputs) && Array.isArray(manifest.files) && manifest.files.length === names.length,
      'Studio build is missing or stale. Run npm run build:studio.');
    let outputBytes = 0;
    for (let index = 0; index < sources.length; index += 1) {
      const source = sources[index], file = manifest.files[index];
      requireThat(file && file.source === source.source && file.output === source.output
        && file.source_bytes === source.source_bytes && file.source_sha256 === source.source_sha256,
        'Studio compiled source is stale: ' + source.source);
      const bytes = readFile(path.join(output, source.output), 2 * 1024 * 1024);
      requireThat(file.bytes === bytes.length && file.sha256 === digest(bytes)
        && file.integrity === 'sha256-' + createHash('sha256').update(bytes).digest('base64'),
        'Studio compiled output is stale or corrupt: ' + source.output);
      outputBytes += bytes.length;
    }
    requireThat(outputBytes <= 4 * 1024 * 1024, 'Studio output exceeds its aggregate bound.');
    const vendor = vendorOutputs();
    requireThat(same(manifest.vendor, vendor.map(item => item.record)), 'Studio vendor bundle is stale. Run npm run build:studio.');
    for (const item of vendor) requireThat(digest(readFile(path.join(output, item.record.output), 1024 * 1024)) === item.record.sha256,
      'Studio vendor output is stale or corrupt: ' + item.record.output);
    console.log(JSON.stringify({ok:true, action:'check', files:names.length, output_bytes:outputBytes}));
    return;
  }

  // The package is type:module. Load the reviewed standalone UMD bytes into an
  // isolated build context, never require it as an ESM application dependency.
  const Babel = {};
  const vendor = readFile(path.join(studio, 'vendor', 'babel.js'), 4 * 1024 * 1024);
  vm.runInNewContext(vendor.toString('utf8'), {exports:Babel, module:{exports:Babel}},
    {filename:'studio/vendor/babel.js', timeout:10000});
  requireThat(Babel.version === version && typeof Babel.transform === 'function',
    'Vendored Babel changed; review transformScriptTags defaults before building.');
  const outputs = sources.map(source => {
    const filename = '/studio/' + source.source;
    const result = Babel.transform(source.text, {...options, filename, sourceFileName:filename});
    requireThat(result && typeof result.code === 'string', 'Studio transform produced no classic script.');
    // Separate outputs preserve script-level declaration/redefinition timing.
    // Never wrap them in an IIFE/module or concatenate their global scopes.
    const bytes = Buffer.from(result.code + '\n', 'utf8');
    requireThat(bytes.length <= 2 * 1024 * 1024, 'Compiled Studio script exceeds its bound.');
    new vm.Script(result.code, {filename:source.output}); // Parse only; no app code executes here.
    return {bytes, record:{source:source.source, output:source.output,
      source_bytes:source.source_bytes, source_sha256:source.source_sha256,
      bytes:bytes.length, sha256:digest(bytes),
      integrity:'sha256-' + createHash('sha256').update(bytes).digest('base64')}};
  });
  const outputBytes = outputs.reduce((sum, item) => sum + item.bytes.length, 0);
  requireThat(outputBytes <= 4 * 1024 * 1024, 'Studio output exceeds its reviewed 4 MiB aggregate bound.');
  requireThat(same(heldInputs, inputs()) && same(sources.map(({text, ...file}) => file),
    sourceFiles().map(({text, ...file}) => file)), 'Studio inputs changed during compilation; no output published.');
  const bundle = vendorOutputs();
  const manifest = {format:1, babel_version:version, options, inputs:heldInputs,
    files:outputs.map(item => item.record), vendor:bundle.map(item => item.record)};
  const manifestBytes = Buffer.from(JSON.stringify(manifest, null, 2) + '\n');
  requireThat(manifestBytes.length <= 32 * 1024, 'Studio build manifest exceeds its bound.');
  generatedDirectory(true);
  for (const item of [...bundle, ...outputs]) writeAtomic(item.record.output, item.bytes);
  // Publish the admission record last. Partial/interrupted output fails SRI/check.
  writeAtomic('manifest.json', manifestBytes);
  console.log(JSON.stringify({ok:true, action:'compile', files:names.length, output_bytes:outputBytes,
    manifest_sha256:digest(manifestBytes), babel_version:version}));
}
try { main(); } catch (error) {
  console.error('Studio precompile refused: ' + error.message);
  process.exitCode = 1;
}
