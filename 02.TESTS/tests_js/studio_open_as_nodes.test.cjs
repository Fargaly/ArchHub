/* "Open as nodes" on a workflow card must walk the workflow's own scope (where its step
   nodes draw) through the existing scope-open path, then focus and switch to the canvas.
   A workflow whose scope_path does not end at its scope is refused with a message and the
   mode never switches. Pure helper; no React, no app, no network. */
const test = require('node:test');
const assert = require('node:assert/strict');

// ── source: openAsNodes routes through the helper (not a bare focus+mode) ──

// ── walk: a workflow with a valid scope_path is walked, then focus + canvas ──

// ── walk: with no signed authority, it uses ARCHHUB_SCOPE_OPEN (the only other path) ──

// ── refuse: a scope_path that does not end at the workflow scope → message, no switch ──

// ── refuse: a null scope_path (server omitted it) → message, no switch ──

// ── failure: an open that throws → message, no switch ──

// ── no workflow: a plain focus (e.g. a session Agent node) just focuses and switches ──

// The real card handler: slices BOTH functions and returns the one the workflow card calls.

// ── caller: the workflow card opens ITS workflow (a member focus), walking that scope ──

// ── caller: the card walks ITS workflow's scope, never a selection; a null workflow just switches ──

// ── wfAct refreshes the topology after an accepted mutation (stale-snapshot root cause) ──

// ── epoch: a refresh that resolves after the view moved never overwrites it ──

// ── MOUNTED regression: a real WorkshopView render; clicking the drawn card ⌗ walks ITS workflow ──

// ── OWNER: a stale topology read must not publish across navigation, incl. away-and-back / identity ──

// ── RUNTIME: an accepted workflow action with a failed refresh keeps the receipt, no second POST ──

// INTEG1 preserves the pre-WORKSHOP receipt/no-replay behavior at both the
// visible S1 Run route and the shipped owner retained for workflow approval.

for(const action of ['workflow-approve','workflow-revoke','workflow-draft']){
  test('OWNER '+action+' preserves an accepted receipt and never re-POSTs on refresh failure',async()=>{
    const {transport}=require('./workshop72_regression_helpers.cjs');let posted=false;
    const owner=transport({get:(_url,held)=>{if(posted)throw new Error('refresh boom');return held;},post:()=>{posted=true;return{ok:true};}});
    await owner.api.refreshWorkshop('room-a');
    const fields=action==='workflow-draft'?{message:'reply-1'}:action==='workflow-approve'?{workflow:'wf-1',digest:'d'.repeat(64)}:{workflow:'wf-1'};
    const result=await owner.api.workshopWorkflow('room-a',action,fields);
    assert.equal(result.ok,true);assert.equal(owner.posts.length,1);
    assert.equal(owner.posts[0].body.action,action);assert.equal(owner.posts[0].body.root,'room-a');
    for(const [key,value] of Object.entries(fields))assert.equal(owner.posts[0].body[key],value);
    assert.equal(owner.gets.length,2,'one transcript refresh after the accepted action, never another POST');
  });
}

// D-FIX1 (founder window 2026-10-12: a graph opened at 66% under the toolbar and cut at the left edge).

// ── wiring: the workflow card's ⌗ binds openShownWorkflowAsNodes(shownWorkflow), not openAsNodes ──
