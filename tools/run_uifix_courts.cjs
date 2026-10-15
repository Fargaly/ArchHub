// Focused lane courts only, invoked inside run-heavy. Never the full studio suite.
const fs = require('node:fs');
const {spawnSync, execFileSync} = require('node:child_process');
const base = 'e5f7abcdcd0766e34cd0d8868b151d591f45e871';
const files = fs.readdirSync('tests_js').filter(name => /^studio_.*\.test\.cjs$/.test(name) &&
  /workshop|settings|rail|app_frame|boot_library_failure|mods_engine|uifix/.test(name)).map(name => 'tests_js/' + name).sort();
const inventory = files.map(file => {
  let before = '';
  try {before = execFileSync('git', ['show', base + ':' + file], {encoding:'utf8', stdio:['ignore','pipe','ignore']});} catch {}
  const after = fs.readFileSync(file, 'utf8');
  const count = text => ({test_declarations:(text.match(/\btest\s*\(/g) || []).length,
    assertions:(text.match(/\bassert\.(?:[A-Za-z]+)\s*\(/g) || []).length});
  return {file, before:count(before), after:count(after)};
});
fs.writeFileSync('evidence/uifix-court-inventory.json', JSON.stringify({base, files:inventory}, null, 2) + '\n');
console.log('Target files: ' + files.length);
const result = spawnSync(process.execPath, ['--test', '--test-concurrency=1', '--test-force-exit', ...files], {stdio:'inherit'});
process.exit(result.status ?? 1);
