const {test} = require('node:test');
const assert = require('node:assert/strict');



test('UIFIX: existing store retires dead roster rows on full and unchanged pages without losing history', async () => {
  const {transport} = require('./workshop72_regression_helpers.cjs');
  const f = transport();
  const now = Date.now() / 1000;
  const live = {root:'live', label:'Codex', attached:true, is_agent:true, runtime:'codex',
    connection_status:'connected', connection_basis:'authenticated-request', observed_at:now, expires_at:now+60};
  f.transcript.participants = [live, ...Array.from({length:30}, (_, i) => ({...live, root:'dead-'+i,
    label:'Runtime-'+i, connection_status:'disconnected', expires_at:now-1}))];
  f.transcript.messages = [{root:'historic', sender_root:'dead-1', body:'Retained history'}];
  await f.api.openWorkshop('room-a');
  assert.equal(f.api.getSnapshot().workshop.participants.length, 1);
  assert.equal(f.api.getSnapshot().workshop.messages[0].sender_root, 'dead-1');
  f.transcript.unchanged = true;
  f.transcript.participants = [{...live, connected:true, expires_at:now-1}];
  await f.api.refreshWorkshop('room-a');
  assert.equal(f.api.getSnapshot().workshop.participants.length, 0);
  assert.equal(f.api.getSnapshot().workshop.messages[0].body, 'Retained history');
});
