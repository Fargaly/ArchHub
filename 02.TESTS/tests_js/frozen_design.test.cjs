const test = require('node:test');
const assert = require('node:assert/strict');
const reference = require('../design-reference.json');
const frozenDesignFolder = require('../../03.TOOLS/tools/frozen_design.cjs');

test('the design reference resolves the explicit frozen folder', () => {
  assert.equal(frozenDesignFolder(), reference.folder);
});

test('a missing freeze and a WIP reference fail without fallback', () => {
  const original = reference.folder;
  try {
    reference.folder = original.replace(/v\d+[a-z]?$/i, 'v999999999');
    assert.throws(frozenDesignFolder, /Frozen design folder is missing/);
    reference.folder = original.replace('/04.ARCHIVE/', '/01.WIP/');
    assert.throws(frozenDesignFolder, /must name an absolute frozen/);
  } finally {
    reference.folder = original;
  }
});
