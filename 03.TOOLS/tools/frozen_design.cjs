const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const reference = require('../../02.TESTS/design-reference.json');

module.exports = function frozenDesignFolder() {
  const folder = reference.folder;
  assert.ok(typeof folder === 'string' && path.isAbsolute(folder) && /[\\/]04\.ARCHIVE[\\/]archhub-directions-v\d+[a-z]?$/i.test(folder),
    'Design reference must name an absolute frozen 04.ARCHIVE/archhub-directions-vNN folder; update 02.TESTS/design-reference.json at each freeze.');
  assert.ok(fs.existsSync(folder) && fs.statSync(folder).isDirectory(),
    'Frozen design folder is missing: ' + folder + '; update 02.TESTS/design-reference.json. No WIP fallback is allowed.');
  return folder;
};
