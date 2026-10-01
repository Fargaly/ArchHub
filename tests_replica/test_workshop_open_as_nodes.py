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

from test_workshop_milestone_one import (  # noqa: F401
    harness, _proposal_reply, _draft, _workflow, _message, _send_contact, OPENCODE)


def test_a_general_workshop_draft_at_app_canvas_carries_its_trail(harness):
    """The installed path: a workflow drafted in the GENERAL Workshop (root app:workshop) at the
    top canvas scope app:canvas. Its scope_path must be the verified trail to app:canvas (['app:canvas']),
    not null, so the card can open it. No start-session (that navigates to the workbench)."""
    h = harness
    h.start()
    registry = h.state["server"].universal_registry
    workbench = registry.workshop_workbench_root

    def _enter(root):
        proj = h.request("/api/universal/canvas")
        binding = next((b for b in (proj.get("interaction_projection") or {}).get("bindings", [])
                        if b.get("control") == root), None)
        assert binding, ("no interaction binding for %s" % root, [b.get("control") for b in (proj.get("interaction_projection") or {}).get("bindings", [])])
        h.request("/api/universal/interaction", {"interaction": binding["interaction"], "control": root,
            "event": binding["event"], "revision": proj["revision"],
            "projection_mode": binding.get("acknowledgement_mode") or "receipt-v1"})

    # Fresh start sits at the top canvas; the real installed Workshop canvas is app:canvas.
    assert h.request("/api/universal/canvas")["scope"]["current"] == "app:canvas"

    # Navigate to the workbench to bind/send the agent (native_contact.py:112 requires that scope),
    # propose there, then navigate back to app:canvas and DRAFT there (the installed client stamp).
    _enter("gm:domain:brain")
    _enter(workbench)
    page = h.page("app:workshop", workbench)
    bound = h.request("/api/universal/native-contact", {"action": "bind", "root": "app:workshop",
        "scope": workbench, "node": None, "app": "opencode", "session_id": OPENCODE["id"],
        "revision": page["revision"]})
    convo = {"root": "app:workshop", "scope": workbench}
    asked = _send_contact(h, convo, bound["contact"], bound["binding_digest"],
        "PROPOSE a workflow: you build the release note, Claude reviews it.", "general-propose")
    h.settle()
    reply_id = _message(h.page("app:workshop", workbench), asked["message_id"])["delivery"][0]["reply_message_id"]

    # Back to the top canvas, then draft the way the installed Workshop stamps it: scope = canvas.root.
    h.request("/api/universal/graph-open", {"root": registry.canvas_root})
    top = h.request("/api/universal/canvas")
    assert top["scope"]["current"] == "app:canvas", top["scope"]
    drafted = h.request("/api/universal/workshop", {"action": "workflow-draft", "root": "app:workshop",
        "scope": "app:canvas", "message": reply_id, "idempotency_key": "general-draft",
        "revision": top["revision"]})
    rows = [r for r in h.page("app:workshop", "app:canvas")["workflows"] if r["root"] == drafted["workflow"]]
    assert rows, "the general-Workshop workflow is listed at app:canvas"
    row = rows[0]
    assert row["scope"] == "app:canvas", (row["scope"],)
    assert row["scope_path"] == ["app:canvas"], row["scope_path"]  # RED on cf218ae5: None
    # The member nodes are in the canvas projection, as ordinary (non-application) nodes.
    cnodes = {n["id"]: n for n in h.request("/api/universal/canvas")["nodes"]}
    for member in row["members"]:
        assert member in cnodes, (member, "member absent from canvas nodes")
        assert cnodes[member].get("application") is not True, (member, "member must not be application-only")


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
