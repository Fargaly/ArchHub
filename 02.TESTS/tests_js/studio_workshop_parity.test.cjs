/* Workshop design parity, items 1/3/5/6 (717 order 2026-10-01): the agents rail names an agent by
   its host and says what is not reported; a proposal waiting on the founder reads NEEDS YOU and
   counts; the header carries the Work title and the probed host; the workflow card is the latest
   agent-proposed workflow with its approval chip, Revoke and Re-approve; the context panel shows a
   proposal's requested permissions and an agent's assigned Work. Real projections only. */
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '..', '..');
const read = name => fs.readFileSync(path.join(root, name), 'utf8');

// A live-shaped fixture: studio-existing-workshop.js snapshot, projectStudioCanvas nodes and wires.

// Visible text as a reader meets it: every text node, in order, separated by one space.

test('server: the participant host comes from the runtime catalog; revoke is a workflow action of the one route', () => {
  const conversation = read('01.APP/nodelang/existing_workshop_conversation.py');
  assert.match(conversation, /row\["host"\] = workshop_runtime_host\(row\.get\("runtime"\)\)/);
  assert.match(conversation, /from \.universal_application import _HARNESS_AGENT_RUNTIMES/);
  const flow = read('01.APP/nodelang/workshop_workflow.py');
  assert.match(flow, /ACTIONS = frozenset\(\{[^}]*"workflow-revoke"/);
  assert.match(flow, /"workflow-revoke": revoke_workflow/);
  assert.match(read('01.APP/nodelang/studio/studio-existing-workshop.js'), /\['workflow-draft', 'workflow-approve', 'workflow-revoke', 'workflow-execute', 'artifact-review'\]/);
});
