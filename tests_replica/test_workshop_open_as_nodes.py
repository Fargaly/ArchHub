"""Open-as-nodes server contract: a workflow row carries a scope_path that ends at the
workflow's own scope, so the canvas can walk there and draw its step nodes.

Real application end to end (the milestone-one harness): start a session, an agent proposes
a workflow, the user drafts it, then workflow_state is read through the real
/api/universal/workshop route. No text anchor, no monkeypatch.

OPEN (deferred): a workflow drafted from a saved room or another non-workbench scope. Its
draft scope is not the workbench, so workshop_workbench_path does not end at it and
scope_path is emitted as null (fail-closed) -- the canvas never opens the wrong scope, and
the client refuses with a message (courted in tests_js/studio_open_as_nodes.test.cjs). The
preferred handling (walk the admitted workbench path plus the verified registered room scope,
or the current verified scope/trail) is not yet implemented.
"""
import pytest

from test_workshop_milestone_one import harness, _proposal_reply, _draft, _workflow  # noqa: F401


def test_workflow_row_scope_path_ends_at_the_workflow_scope(harness):
    h = harness
    h.start()
    convo = h.conversation_with_two_agents()
    reply_id = _proposal_reply(h, convo)
    drafted = _draft(h, convo, reply_id, "open-as-nodes-scope-path")
    row = _workflow(h, convo, drafted["workflow"])

    assert "scope" in row and row["scope"], row
    assert "scope_path" in row, "the workflow row must carry a scope_path for Open-as-nodes"
    assert isinstance(row["scope_path"], list) and row["scope_path"], "scope_path is a non-empty walk"
    assert row["scope_path"][-1] == row["scope"], "the walk must END at the workflow's own scope"
    # A session draft lives on the Workshop workbench; that is where the step nodes draw.
    registry = h.state["server"].universal_registry
    assert row["scope"] == registry.workshop_workbench_root
