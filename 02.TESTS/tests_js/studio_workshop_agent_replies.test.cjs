/* An agent's relayed reply in the Workshop thread (founder-blocking, 2026-10-01): on the default
   messages feed the reply was invisible and the founder's message stayed STARTED. The reply is now
   an agent row named by the relay's own header (never the contact root), its message reads
   REPLIED, "Draft as workflow" is on it, and the workflow card names its proposer the same way. */
const {test} = require('node:test');
const assert = require('node:assert/strict');

// A live-shaped fixture: studio-existing-workshop.js snapshot, projectStudioCanvas nodes and wires.

// Visible text as a reader meets it: every text node, in order, separated by one space.

const {transport}=require('./workshop72_regression_helpers.cjs');

test('removed Properties draft route still binds exact reply and retains accepted receipt after refresh refusal',async()=>{
  let posted=false;const fx=transport({get:(_url,held)=>{if(posted)throw new Error('refresh boom');return held;},post:()=>{posted=true;return{ok:true,draft:'wf-1'};}});
  await fx.api.refreshWorkshop('room-a');const result=await fx.api.workshopWorkflow('room-a','workflow-draft',{message:'reply-1'});
  assert.equal(result.ok,true);assert.equal(result.draft,'wf-1');assert.equal(fx.posts.length,1);
  assert.equal(fx.posts[0].body.message,'reply-1');assert.equal(fx.posts[0].body.action,'workflow-draft');assert.match(fx.posts[0].body.idempotency_key,/^draft-/);
});
