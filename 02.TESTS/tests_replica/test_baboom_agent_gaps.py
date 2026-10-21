from types import SimpleNamespace

import pytest

from nodelang import app_brain
from tests_replica.test_goose_brain import packaged
from nodelang.baboom_owner_grants import (
    GRANT_ARGUMENT_KEY,
    APPROVAL_PREFIX,
    baboom_brain_write_arguments_digest,
    baboom_brain_write_owner_approval_record,
)
from nodelang.brain_store_port import FOUNDER_OWNER_ROOT, ensure_port_session
from nodelang.cell_brain_memory import remember
from nodelang.cell_catalog import bootstrap_assembly_protocol
from nodelang.native_agentic_loop import ToolSpec, run_agentic_tool_loop
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore
from nodelang.workshop_session_start import (
    _baboom_owner_grant_checker,
    _baboom_owner_tool_bridge,
    _tool_steps_record,
)


def _call(name, arguments=None, ident=None):
    return {"id": ident or name, "name": name, "arguments": arguments or {}}


def _run(script, host, grant=None):
    turns = iter(script)

    def model_turn(_rows, _schemas):
        return next(turns)

    return run_agentic_tool_loop(
        model_turn,
        # These are fixtures for the retained Workshop owner's grant/readback
        # contract. BABOOM no longer exposes brain.write; Goose's MCP surface
        # and its zero-write permission court are in test_goose_brain.py.
        {"brain.context": ToolSpec("brain.context", lambda name, args: host(name, args)) if host else
            ToolSpec("brain.context", lambda *_: {"ok": False, "status": "unavailable", "error": "owner unavailable"}),
         "brain.write": ToolSpec("brain.write", lambda name, args: host(name, args), mutates=True,
            verify=lambda _name, _args, _result: host("brain.context", {}))},
        [{"role": "user", "content": "test"}],
        grant_checker=grant,
        max_steps=8,
    )


def _approval_checker(store, registry, *, workflow=None):
    return _baboom_owner_grant_checker(
        store, registry, workflow_root=workflow or registry.workshop_root)


def _approved_brain_write(store, registry, arguments, *, workflow=None, scope="scope:test"):
    """Low-level persisted grant fixture; route issuance is covered by the HTTP courts."""
    workflow = workflow or registry.workshop_root
    approved = dict(arguments)
    approved[GRANT_ARGUMENT_KEY] = baboom_brain_write_owner_approval_record(
        store,
        owner=registry.authorization.subject_root,
        actor=registry.authorization.subject_root,
        session=registry.agent_body.session.root_id,
        workflow=workflow,
        scope=scope,
        approval_digest="a" * 64,
        workflow_revision=store.revision + 1,
        arguments=arguments,
    )
    return approved


@pytest.fixture
def graph_brain():
    store = CellStore()
    protocol = bootstrap_assembly_protocol(store)
    store.commit(store.snapshot().revision, create=(
        Cell(FOUNDER_OWNER_ROOT, NULL_CELL_ID, NULL_CELL_ID, b"founder"),))
    session = ensure_port_session(store)
    remember(store, session_root=session, fragment_id="f-existing", text="Existing graph fact",
             kind="fact", origin="court", clock=1000, confidence="extracted")
    registry = SimpleNamespace(authorization=SimpleNamespace(subject_root=FOUNDER_OWNER_ROOT),
                               workshop_root="workflow:test",
                               application_root="application:test",
                               agent_body=SimpleNamespace(session=SimpleNamespace(root_id=FOUNDER_OWNER_ROOT)),
                               assembly_protocol=protocol)
    app_brain.bind(store, registry)
    yield store, registry
    app_brain.unbind(store)


def test_unowned_brain_read_refuses_instead_of_reporting_empty_memory():
    result = _run([
        {"tool_calls": [_call("brain.context", {"prompt": "anything"})]},
        {"answer": "done"},
    ], host=None)

    assert result["steps"][0]["status"] == "unavailable"
    assert result["steps"][0]["ok"] is False


def test_brain_write_uses_the_graph_brain_ops_contract(graph_brain):
    store, registry = graph_brain
    bridge = _baboom_owner_tool_bridge(store, registry)
    arguments = _approved_brain_write(store, registry, {"ops": [
        {"op": "add", "fragment": {"id": "f-new", "kind": "fact", "text": "Project code P-999"}}
    ]}, workflow="workflow:graph-contract")

    result = _run([
        {"tool_calls": [_call("brain.write", arguments)]},
        {"answer": "done"},
    ], host=bridge, grant=_approval_checker(store, registry, workflow="workflow:graph-contract"))

    assert result["steps"][0]["status"] == "ok"
    held = app_brain.call("brain.list_facts", {"limit": 10})
    facts = [row for folder in held["folders"] for row in folder["facts"]]
    assert any(row["body"] == "Project code P-999" for row in facts)


def test_brain_write_rejects_text_payload_shape(graph_brain, packaged):
    store, registry = graph_brain
    from nodelang.goose_adapter import GooseAdapter, GooseRefused
    # Brain writes were removed from BABOOM, including malformed text writes.
    # The engine cannot bypass that restriction with a permission request.
    packaged.mode[0] = "permission"
    packaged.runtime.start()
    with pytest.raises(GooseRefused, match="No action was approved"):
        GooseAdapter(packaged.runtime).ask("Remember project code P-999", "", "openrouter/free")
    assert packaged.calls == []


def test_approved_brain_write_passes_once(graph_brain):
    store, registry = graph_brain
    bridge = _baboom_owner_tool_bridge(store, registry)
    writes = []

    def counting_host(action, arguments):
        if action == "brain.write":
            writes.append(dict(arguments))
        return bridge(action, arguments)

    arguments = _approved_brain_write(store, registry, {"ops": [
        {"op": "add", "fragment": {"id": "f-once", "kind": "fact", "text": "Write once"}}
    ]}, workflow="workflow:once")

    result = _run([
        {"tool_calls": [
            _call("brain.write", arguments, ident="write-one"),
            _call("brain.write", arguments, ident="write-two"),
        ]},
        {"answer": "done"},
    ], host=counting_host, grant=_approval_checker(store, registry, workflow="workflow:once"))

    assert result["steps"][0]["status"] == "ok"
    assert result["steps"][1]["status"] == "refused"
    assert len(writes) == 1
    held = app_brain.call("brain.list_facts", {"limit": 10})
    facts = [row for folder in held["folders"] for row in folder["facts"]]
    assert sum(row["body"] == "Write once" for row in facts) == 1


def test_approved_brain_write_refuses_different_owner_with_zero_writes(graph_brain):
    store, registry = graph_brain
    bridge = _baboom_owner_tool_bridge(store, registry)
    writes = []

    def counting_host(action, arguments):
        if action == "brain.write":
            writes.append(dict(arguments))
        return bridge(action, arguments)

    arguments = _approved_brain_write(store, registry, {"ops": [
        {"op": "add", "fragment": {"id": "f-other-owner", "kind": "fact", "text": "Other owner"}}
    ]}, workflow="workflow:owner-bound")
    other_registry = SimpleNamespace(
        authorization=SimpleNamespace(subject_root="owner:other"),
        workshop_root=registry.workshop_root,
        application_root=registry.application_root,
        agent_body=registry.agent_body,
    )

    result = _run([
        {"tool_calls": [_call("brain.write", arguments)]},
        {"answer": "done"},
    ], host=counting_host, grant=_approval_checker(
        store, other_registry, workflow="workflow:owner-bound"))

    assert result["steps"][0]["status"] == "refused"
    assert len(writes) == 0


def test_approved_brain_write_refuses_changed_workflow_with_zero_writes(graph_brain):
    store, registry = graph_brain
    bridge = _baboom_owner_tool_bridge(store, registry)
    writes = []

    def counting_host(action, arguments):
        if action == "brain.write":
            writes.append(dict(arguments))
        return bridge(action, arguments)

    arguments = _approved_brain_write(store, registry, {"ops": [
        {"op": "add", "fragment": {"id": "f-edited-workflow", "kind": "fact", "text": "Edited workflow"}}
    ]}, workflow="workflow:edited")
    store.commit(store.revision, create=(
        Cell("workflow:edited:after-approval", NULL_CELL_ID, NULL_CELL_ID, b"changed"),))

    result = _run([
        {"tool_calls": [_call("brain.write", arguments)]},
        {"answer": "done"},
    ], host=counting_host, grant=_approval_checker(store, registry, workflow="workflow:edited"))

    assert result["steps"][0]["status"] == "refused"
    assert len(writes) == 0


def test_approved_brain_write_survives_restart_and_consumes_once(tmp_path):
    path = tmp_path / "brain-write-approval.sqlite3"
    store = CellStore(path)
    protocol = bootstrap_assembly_protocol(store)
    store.commit(store.snapshot().revision, create=(
        Cell(FOUNDER_OWNER_ROOT, NULL_CELL_ID, NULL_CELL_ID, b"founder"),))
    session = ensure_port_session(store)
    registry = SimpleNamespace(authorization=SimpleNamespace(subject_root=FOUNDER_OWNER_ROOT),
                               workshop_root="workflow:restart",
                               application_root="application:test",
                               agent_body=SimpleNamespace(session=SimpleNamespace(root_id=FOUNDER_OWNER_ROOT)),
                               assembly_protocol=protocol)
    app_brain.bind(store, registry)
    arguments = _approved_brain_write(store, registry, {"ops": [
        {"op": "add", "fragment": {"id": "f-restart", "kind": "fact", "text": "Restarted once"}}
    ]}, workflow="workflow:restart")
    app_brain.unbind(store)
    store.close()

    reopened = CellStore(path)
    registry = SimpleNamespace(authorization=SimpleNamespace(subject_root=FOUNDER_OWNER_ROOT),
                               workshop_root="workflow:restart",
                               application_root="application:test",
                               agent_body=SimpleNamespace(session=SimpleNamespace(root_id=FOUNDER_OWNER_ROOT)),
                               assembly_protocol=protocol)
    app_brain.bind(reopened, registry)
    bridge = _baboom_owner_tool_bridge(reopened, registry)
    try:
        result = _run([
            {"tool_calls": [
                _call("brain.write", arguments, ident="write-one"),
                _call("brain.write", arguments, ident="write-two"),
            ]},
            {"answer": "done"},
        ], host=bridge, grant=_approval_checker(reopened, registry, workflow="workflow:restart"))

        assert result["steps"][0]["status"] == "ok"
        assert result["steps"][1]["status"] == "refused"
        held = app_brain.call("brain.list_facts", {"limit": 10})
        facts = [row for folder in held["folders"] for row in folder["facts"]]
        assert sum(row["body"] == "Restarted once" for row in facts) == 1
    finally:
        app_brain.unbind(reopened)
        reopened.close()


def test_changed_brain_write_args_refuse_with_zero_owner_writes(graph_brain):
    store, registry = graph_brain
    bridge = _baboom_owner_tool_bridge(store, registry)
    writes = []

    def counting_host(action, arguments):
        if action == "brain.write":
            writes.append(dict(arguments))
        return bridge(action, arguments)

    original = {"ops": [
        {"op": "add", "fragment": {"id": "f-original", "kind": "fact", "text": "Original"}}
    ]}
    changed = _approved_brain_write(store, registry, original, workflow="workflow:changed")
    changed["ops"] = [
        {"op": "add", "fragment": {"id": "f-changed", "kind": "fact", "text": "Changed"}}
    ]

    result = _run([
        {"tool_calls": [_call("brain.write", changed)]},
        {"answer": "done"},
    ], host=counting_host, grant=_approval_checker(store, registry, workflow="workflow:changed"))

    assert result["steps"][0]["status"] == "refused"
    assert len(writes) == 0
    held = app_brain.call("brain.list_facts", {"limit": 10})
    facts = [row for folder in held["folders"] for row in folder["facts"]]
    assert all(row["body"] != "Changed" for row in facts)


def test_self_minted_brain_write_grant_refuses_with_zero_owner_writes(graph_brain):
    store, registry = graph_brain
    bridge = _baboom_owner_tool_bridge(store, registry)
    writes = []

    def counting_host(action, arguments):
        if action == "brain.write":
            writes.append(dict(arguments))
        return bridge(action, arguments)

    arguments = {"ops": [
        {"op": "add", "fragment": {"id": "f-forged", "kind": "fact", "text": "Forged grant"}}
    ]}
    forged = dict(arguments)
    forged[GRANT_ARGUMENT_KEY] = {
        "kind": "baboom-owner-brain-write-approval",
        "version": 1,
        "tool": "brain.write",
        "owner": FOUNDER_OWNER_ROOT,
        "actor": FOUNDER_OWNER_ROOT,
        "session": FOUNDER_OWNER_ROOT,
        "workflow": "workflow:forged",
        "workflow_revision": store.revision,
        "scope": "scope:forged",
        "approval_id": APPROVAL_PREFIX + "caller-built",
        "approval_digest": "a" * 64,
        "arguments_digest": baboom_brain_write_arguments_digest(arguments),
    }

    result = _run([
        {"tool_calls": [_call("brain.write", forged)]},
        {"answer": "done"},
    ], host=counting_host, grant=_approval_checker(store, registry, workflow="workflow:forged"))

    assert result["steps"][0]["status"] == "refused"
    assert len(writes) == 0
    held = app_brain.call("brain.list_facts", {"limit": 10})
    facts = [row for folder in held["folders"] for row in folder["facts"]]
    assert all(row["body"] != "Forged grant" for row in facts)


def test_unsolicited_brain_write_refuses_with_zero_owner_writes(graph_brain):
    store, registry = graph_brain
    bridge = _baboom_owner_tool_bridge(store, registry)
    writes = []

    def counting_host(action, arguments):
        if action == "brain.write":
            writes.append(dict(arguments))
        return bridge(action, arguments)

    result = _run([
        {"tool_calls": [_call("brain.write", {"ops": [
            {"op": "add", "fragment": {"id": "f-unsolicited", "kind": "fact", "text": "No grant"}}
        ]})]},
        {"answer": "done"},
    ], host=counting_host, grant=_approval_checker(store, registry))

    assert result["steps"][0]["status"] == "refused"
    assert len(writes) == 0
    held = app_brain.call("brain.list_facts", {"limit": 10})
    facts = [row for folder in held["folders"] for row in folder["facts"]]
    assert all(row["body"] != "No grant" for row in facts)


def test_plan_approval_is_not_a_same_turn_host_write_grant(graph_brain):
    store, registry = graph_brain
    bridge = _baboom_owner_tool_bridge(store, registry)

    result = _run([
        {"tool_calls": [_call("plan.propose", {"steps": [{"title": "Change host"}]})]},
        {"tool_calls": [_call("host.write", {"target": "n1", "patch": {"status": "done"}})]},
        {"answer": "done"},
    ], host=bridge)

    assert result["steps"][0]["status"] == "refused"
    assert "tool is not allowed" in result["steps"][0]["summary"]
    assert result["steps"][1]["status"] == "refused"
    assert "tool is not allowed" in result["steps"][1]["summary"]


def test_host_write_needs_an_approved_plan_binding(graph_brain):
    store, registry = graph_brain
    bridge = _baboom_owner_tool_bridge(store, registry)

    result = _run([
        {"tool_calls": [_call("host.write", {"target": "n1", "patch": {"status": "done"}})]},
        {"answer": "done"},
    ], host=bridge, grant=lambda _name, _args: True)

    assert result["steps"][0]["status"] == "refused"
    assert "tool is not allowed" in result["steps"][0]["summary"]


def test_mutating_step_fails_when_owner_readback_refuses():
    turns = iter([
        {"tool_calls": [_call("owned.write", {"target": "n1"})]},
        {"answer": "done"},
    ])

    result = run_agentic_tool_loop(
        lambda _rows, _schemas: next(turns),
        {"owned.write": ToolSpec(
            "owned.write",
            lambda _name, _args: {"ok": True, "written": "n1"},
            mutates=True,
            verify=lambda _name, _args, _result: {
                "ok": False, "status": "refused", "error": "readback refused"},
        )},
        [{"role": "user", "content": "test"}],
        grant_checker=lambda _name, _args: True,
    )

    assert result["steps"][0]["status"] == "failed"
    assert "verification failed" in result["steps"][0]["summary"]


def test_save_as_skill_refuses_without_a_governed_skill_writer(graph_brain):
    store, registry = graph_brain
    bridge = _baboom_owner_tool_bridge(store, registry)

    result = _run([
        {"tool_calls": [_call("skill.save", {"title": "Prepare transmittal"})]},
        {"answer": "done"},
    ], host=bridge)

    assert result["steps"][0]["status"] == "refused"
    assert "tool is not allowed" in result["steps"][0]["summary"]


def test_workshop_reply_uses_central_redaction_for_visible_tool_steps():
    fake_bearer = "Bearer " + ("a" * 26) + ("Z" * 26) + "0123456789"
    fake_github = "github_pat_" + ("A" * 24) + "_0123456789"
    fake_slack = "xoxb-" + ("1" * 12) + "-" + ("2" * 12)
    fake_google = "AIza" + ("A" * 24)
    text = _tool_steps_record([
        {"tool": "host.write", "status": "ok",
         "summary": "patched token=secret123456 %s %s" % (fake_bearer, fake_github),
         "readback": "checked %s %s" % (fake_slack, fake_google)},
    ])

    assert "Tool steps:" in text
    assert "token=[redacted]" in text
    assert "[redacted]" in text
    for secret in (fake_bearer, fake_github, fake_slack, fake_google, "secret123456"):
        assert secret not in text
