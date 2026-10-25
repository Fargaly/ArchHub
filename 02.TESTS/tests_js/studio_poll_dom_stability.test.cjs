
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '..', '..');
const read = name => fs.readFileSync(path.join(root, name), 'utf8');

const scope = () => ({graph_id:'graph-a', root:'scope-a', revision:7,
  workshops:[{root:'room-a', label:'General Workshop', is_general:true}]});

test('the Workshop projection does not publish when a poll repeats the same scope values', () => {
  const vm = require('./studio_ds_context.cjs');
  const context = vm.createContext({URLSearchParams, TextEncoder});
  vm.runInContext(read('01.APP/nodelang/studio/studio-existing-workshop.js'), context);
  const api = context.ArchHubExistingWorkshop.create({get:async () => ({}), post:async () => ({})});
  let publishes = 0;
  api.subscribe(() => { publishes += 1; });
  api.setCanvas(scope());
  assert.equal(publishes, 1, 'first scope poll publishes the visible projection');
  api.setCanvas(scope());
  assert.equal(publishes, 1, 'same-value scope poll is not a new projection');
});
