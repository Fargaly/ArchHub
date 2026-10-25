/* Workshop "Assign to agent" (design workshop-assign-design.html, founder decisions 1-5): the ASSIGN
   section of the Work's context panel, rendered from the shipped JSX through esbuild in a real browser DOM.
   Only the rail's verified agents can be picked; nothing lets anyone type or start a session; the
   review card says what assigning does and does not do; a refusal leaves nothing assigned; a lost
   reply is retried with the SAME assignment id. The assign call is a stand-in for the transport. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..', '..');
const read = name => fs.readFileSync(path.join(root, name), 'utf8');

test('the Workshop API marks a failure before dispatch as preflight and sends nothing', async () => {
  const vm = require('node:vm');
  const context = vm.createContext({crypto: require('node:crypto').webcrypto, console});
  vm.runInContext(read('01.APP/nodelang/studio/studio-existing-workshop.js'), context);
  const posts = [];
  const api = context.ArchHubExistingWorkshop.create({
    get: async () => ({ok:false}), post: async (...args) => { posts.push(args); return {ok:true}; },
    pendingStorage: {getItem: () => null, setItem: () => {}, removeItem: () => {}}, projectCanvas: () => null,
  });
  await assert.rejects(api.assignWork('app:workshop', {work:'app:governed-work:x', agent_session:'app:agent-session:runtime:717',
    assignment_id:'app:workshop-assignment:abcdef0123456789'}), error => error.assignmentPreflight === true);
  assert.equal(posts.length, 0, 'nothing was sent');
});

test('only a refusal naming the exact assignment id is a refusal; a null or malformed reply stays uncertain', () => {
  const vm = require('node:vm');
  const context = vm.createContext({crypto: require('node:crypto').webcrypto, console});
  vm.runInContext(read('01.APP/nodelang/studio/studio-existing-workshop.js'), context);
  const classify = context.ArchHubExistingWorkshop.classifyAssignmentReply;
  const ask = {assignment_id:'app:workshop-assignment:abcdef0123456789', work:'app:governed-work:x',
    agent_session:'app:agent-session:runtime:717'};
  const refusal = (body) => Object.assign(new Error('refused'), {response: body});
  assert.equal(classify(null, null, ask).kind, 'uncertain', 'a null reply after the commit is not a refusal');
  assert.equal(classify(undefined, null, ask).kind, 'uncertain');
  assert.equal(classify({ok:false}, null, ask).kind, 'uncertain', 'a bare ok:false names no id');
  assert.equal(classify('nonsense', null, ask).kind, 'uncertain');
  assert.equal(classify(null, new Error('network'), ask).kind, 'uncertain');
  assert.equal(classify(null, refusal({refused:true, assignment:'app:workshop-assignment:someone-else'}), ask).kind,
    'uncertain', 'a refusal of another id settles nothing here');
  assert.equal(classify(null, refusal({refused:true}), ask).kind, 'uncertain');
  assert.equal(classify(null, refusal({refused:true, assignment:ask.assignment_id, error:'lapsed'}), ask).kind,
    'uncertain', 'a refusal that does not reconcile the id as absent settles nothing');
  assert.equal(classify(null, refusal({refused:true, assignment:ask.assignment_id, reconciled_absent:true, error:'lapsed'}), ask).kind, 'refused');
  assert.equal(classify({ok:true, assignment:ask.assignment_id, work:ask.work, agent_session:ask.agent_session}, null, ask).kind, 'assigned');
  assert.equal(classify({ok:true, assignment:'app:workshop-assignment:other', work:ask.work, agent_session:ask.agent_session}, null, ask).kind, 'uncertain');
});
