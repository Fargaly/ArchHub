/* Explicit Studio precompile. No watcher, network, application, or provider. */
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {createHash, randomUUID} = require('node:crypto');

const root = path.resolve(__dirname, '..');
const studio = path.join(root, 'nodelang', 'studio');
const output = path.join(studio, 'compiled');
const names = ['tokens.jsx', 'design-canvas.jsx', 'shared-data.jsx', 'studio-suite.jsx',
  'param-types.jsx', 'studio-params.jsx', 'studio-mobile.jsx', 'studio-account.jsx',
  'studio-lm.jsx', 'mount.jsx'];
const version = '7.29.0';
// These are the actual classic-script defaults in this vendored version's
// transformScriptTags/SEe function. Only its inline source maps are omitted.
const options = {presets:['react', 'env'], plugins:['transform-class-properties',
  'transform-object-rest-spread', 'transform-flow-strip-types'], targets:{}, sourceMaps:false};
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
  const bytes = readFile(path.join(root, relative), limit);
  return {path:relative, bytes:bytes.length, sha256:digest(bytes)};
}
function inputs() {
  return {
    compiler:input('packaging/compile_studio.cjs', 128 * 1024),
    babel:input('nodelang/studio/vendor/babel.js', 4 * 1024 * 1024),
    loader:input('nodelang/studio/studio.html', 256 * 1024),
    package:input('package.json', 128 * 1024),
  };
}
function sourceFiles() {
  const files = names.map(source => {
    const bytes = readFile(path.join(studio, source), 512 * 1024);
    return {source, output:source.replace(/\.jsx$/, '.js'), source_bytes:bytes.length,
      source_sha256:digest(bytes), text:new TextDecoder('utf-8', {fatal:true}).decode(bytes)};
  });
  requireThat(files.reduce((sum, file) => sum + file.source_bytes, 0) <= 2 * 1024 * 1024,
    'Studio sources exceed the reviewed 2 MiB aggregate bound.');
  return files;
}
function generatedDirectory(create) {
  if (create) fs.mkdirSync(output, {recursive:true});
  const info = fs.lstatSync(output);
  requireThat(info.isDirectory() && !info.isSymbolicLink(), 'Studio compiled output must be a real directory.');
}
function writeAtomic(name, bytes) {
  requireThat(name === 'manifest.json' || names.some(source => source.replace(/\.jsx$/, '.js') === name),
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
  const manifest = {format:1, babel_version:version, options, inputs:heldInputs,
    files:outputs.map(item => item.record)};
  const manifestBytes = Buffer.from(JSON.stringify(manifest, null, 2) + '\n');
  requireThat(manifestBytes.length <= 32 * 1024, 'Studio build manifest exceeds its bound.');
  generatedDirectory(true);
  for (const item of outputs) writeAtomic(item.record.output, item.bytes);
  // Publish the admission record last. Partial/interrupted output fails SRI/check.
  writeAtomic('manifest.json', manifestBytes);
  console.log(JSON.stringify({ok:true, action:'compile', files:names.length, output_bytes:outputBytes,
    manifest_sha256:digest(manifestBytes), babel_version:version}));
}
try { main(); } catch (error) {
  console.error('Studio precompile refused: ' + error.message);
  process.exitCode = 1;
}
