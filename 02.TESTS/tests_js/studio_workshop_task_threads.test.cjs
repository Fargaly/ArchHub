/* Workshop parity item 4 + C (717 order 2026-10-01): task cards read as the design's T-xx cards whose
   threads are the agents talking about that Work. An agent's relayed reply that names a Work is that
   agent's event on the card (owner, thread sender and text are the agent's, never the relay's header
   or author); thread recipients are named as the rail names them; the task id is derived from the Work
   id (never a counter); no progress bar is drawn because no real progress is projected. C: the agent-
   proposed workflow is approved, revoked and run on its workflow card only, not on a second panel. */
const {test} = require('node:test');
const assert = require('node:assert/strict');

// A live-shaped fixture: studio-existing-workshop.js snapshot, projectStudioCanvas nodes and wires.

// Visible text as a reader meets it: every text node, in order, separated by one space.

const {transport}=require('./workshop72_regression_helpers.cjs');

test('workflow approval revoke and execution retain their exact existing authority route after rich-card removal',async()=>{
  const fx=transport(),D='d'.repeat(64);await fx.api.refreshWorkshop('room-a');
  await fx.api.workshopWorkflow('room-a','workflow-approve',{workflow:'wf-1',digest:D});
  await fx.api.workshopWorkflow('room-a','workflow-revoke',{workflow:'wf-1'});
  await fx.api.workshopWorkflow('room-a','workflow-execute',{workflow:'wf-1'});
  assert.deepEqual(fx.posts.map(post=>[post.url,post.body.root,post.body.action,post.body.workflow]),[
    ['/api/universal/workshop','room-a','workflow-approve','wf-1'],['/api/universal/workshop','room-a','workflow-revoke','wf-1'],
    ['/api/universal/workshop','room-a','workflow-execute','wf-1']]);
  assert.equal(fx.posts[0].body.digest,D);
});
