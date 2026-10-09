"""Court: agents propose governed Work; only the founder's one action binds it (2026-09-30).

An agent still cannot create Work ("governed Work is created by the application
owner; an agent proposes it in the Workshop"). native.work_propose posts that
proposal as an ordinary Workshop message; it creates, grants and admits nothing.
The founder binds a checked set in one action through the browser's creation path
and the one configuration path (CDE grants and reviewers validated, authorization
evidence recorded). A proposal left unchecked stays unbound and grants nothing.

Real persistent server, real machine pipe, real native owner and tools, real CDE
permits behind the real execution gate.
"""
import threading
import time

import pytest

from nodelang import commit_intent
from nodelang import native_agent_mcp as mcp
from nodelang import universal_application as app
from nodelang import work_proposals
from nodelang.application_machine_transport import MachineTransportError
from nodelang.baboom_native_companion import baboom_face_line
from nodelang.existing_workshop_native_host import ExistingWorkshopNativeHost
from nodelang.native_agent_session import NativeAgentSession
from nodelang.universal_cell import InvalidCell
from tests_replica.test_workshop_execution_gate import GATE, TARGET, _agent, _post, _serve

HANDOFF = "70.HANDOFFS/court-proposals"
CONTAINER = {"container_id": "GM.nodes.cde-authority", "source_requirement": "court:proposals",
             "domain": "nodes", "tier": "T1", "suitability_status": "S0", "revision": "P01",
             "owner": "founder", "checker": "court", "gate_kind": "pytest",
             "gate_spec": {"path": "10.PRODUCT/13.NODE-LANGUAGE/tests_replica/test_cell_cde_authority.py"}}
# Two separately scoped roots, each its own grant: a product file and a handoff folder.
GRANTS = [{"path": TARGET, "scope": "exact", "operations": ["apply_patch"]},
          {"path": HANDOFF, "scope": "descendants", "operations": ["apply_patch"]}]


@pytest.fixture
def world(tmp_path, monkeypatch):
    server, descriptor, provider = _serve("content-store", tmp_path, monkeypatch)
    try:
        store, registry = server.universal_store, server.universal_registry
        browser = server._resolve_browser_session(server.browser_session_token)
        with _as_browser(browser):
            app.set_universal_scope(store, registry, registry.map.domains["brain"], authentication_context=browser.context)
            app.set_universal_scope(store, registry, registry.workshop_workbench_root,
                                    authentication_context=browser.context)
        if getattr(server, "_existing_workshop_native_host", None) is None:
            server._existing_workshop_native_host = ExistingWorkshopNativeHost(
                server, state_dir=None, descriptor_path=None, key_provider=None)
        yield server, descriptor, provider, browser
    finally:
        server.close()


def _tools(descriptor, provider, name):
    owner = NativeAgentSession(environment={"CLAUDE_CODE_SESSION_ID": name},
                               descriptor_path=descriptor, key_provider=provider)
    server = mcp.build_server(session=owner)
    return {tool.name: tool.fn for tool in server._tool_manager.list_tools()}, owner.owner_status()["agent_session"]


def _propose(tools, title, *, purpose="general", reviewers=None):
    requirements = {} if reviewers is None else {"artifact_reviewers": reviewers}
    inputs = {"data_class": "public-text", "files": []} if purpose == "artifact-publication" else {}
    return tools["native.work_propose"](title=title, description="proposed by an agent", priority=100,
        purpose=purpose, inputs=inputs, requirements=requirements, container=CONTAINER, write_grants=GRANTS)


def _as_browser(browser):
    """The authenticated browser request's own intent (_resolve_browser_session admits it)."""
    return commit_intent.declare(commit_intent.USER_ACTION, actor=browser.subject_root, reason="court browser request")


def _bind(server, browser, *proposals, tamper=False):
    with _as_browser(browser):
        return _bind_now(server, browser, proposals, tamper)


def _decline(server, browser, proposal, tamper=False):
    registry = server.universal_registry
    with _as_browser(browser):
        return work_proposals.founder_bind_route(server, browser, {
            "action": "decline_work_proposals", "root": registry.workshop_root,
            "scope": registry.workshop_workbench_root, "request_id": "court-decline", "data_class": "public-text",
            "proposals": [{"message_id": proposal["message_id"], "sequence": proposal["sequence"],
                           "digest": ("0" * 64 if tamper else proposal["digest"])}]},
            server.browser_session_token)


def _bind_now(server, browser, proposals, tamper):
    registry = server.universal_registry
    return work_proposals.founder_bind_route(server, browser, {
        "action": "bind_work_proposals", "root": registry.workshop_root,
        "scope": registry.workshop_workbench_root, "request_id": "court-bind", "data_class": "public-text",
        "proposals": [{"message_id": p["message_id"], "sequence": p["sequence"],
                       "digest": ("0" * 64 if tamper else p["digest"])} for p in proposals]},
        server.browser_session_token)


def _proposal_works(server):
    snapshot, registry = server.universal_store.snapshot(), server.universal_registry
    return work_proposals._bound_keys(snapshot, registry)


def test_an_agent_proposes_and_only_the_founders_one_action_binds(world):
    server, descriptor, provider, browser = world
    proposer, me = _tools(descriptor, provider, "court-proposer")
    claimant, _claimant_session = _agent(descriptor, provider, "court-claimant")
    _reviewer, reviewer_session = _agent(descriptor, provider, "court-reviewer")

    first = _propose(proposer, "Proposal A")
    second = _propose(proposer, "Proposal B", purpose="artifact-publication", reviewers=[reviewer_session])
    third = _propose(proposer, "Proposal C")
    assert first["work_created"] is False and first["grants_admitted"] is False
    assert _proposal_works(server) == set()                    # posting admits nothing
    # The proposer can never review its own proposed Work.
    with pytest.raises(MachineTransportError, match="cannot review its own"):
        _propose(proposer, "Self-reviewed", purpose="artifact-publication", reviewers=[me])

    # One action binds exactly the checked two; the third stays a proposal.
    bound = _bind(server, browser, first, second)["bound"]
    assert [row["message_id"] for row in bound] == [first["message_id"], second["message_id"]]
    assert _proposal_works(server) == {"proposal:" + first["message_id"], "proposal:" + second["message_id"]}
    snapshot = server.universal_store.snapshot()
    assert all(row["authorization"] in snapshot.cells for row in bound)   # founder's evidence, per Work
    states = {row["message_id"]: row["state"] for row in proposer["native.work_proposals"]()["proposals"]}
    assert states == {first["message_id"]: "bound", second["message_id"]: "bound", third["message_id"]: "proposed"}
    from nodelang.cell_value_graph import read_value_graph
    registry = server.universal_registry
    def bound_value(work, name):
        target = app._governed_work_interface_target(snapshot, registry, work, name)
        return read_value_graph(snapshot, registry.value_graph_protocol, target)
    assert bound_value(bound[1]["work_root"], "requirements")["artifact_reviewers"] == [reviewer_session]
    container = bound_value(bound[0]["work_root"], "cde-container")
    assert container["write_grants"] == GRANTS and container["allowed_paths"] == [TARGET, HANDOFF]

    # Bound once; a changed proposal is never bound as shown.
    with pytest.raises(InvalidCell, match="already bound"):
        _bind(server, browser, first)
    with pytest.raises(InvalidCell, match="changed since it was shown"):
        _bind(server, browser, third, tamper=True)
    assert "proposal:" + third["message_id"] not in _proposal_works(server)

    # Another agent claims A: writes inside either scoped root are admitted, outside refused.
    work = bound[0]["work_root"]
    assert claimant.claim_work(work)["claimed"] is True
    _post(claimant, "plan", [work], [], "proposal-plan")
    _post(claimant, "research", [work], [], "proposal-research", capture=TARGET)

    def permit(path, key):
        return claimant.issue_cde_write_permit(operation="apply_patch", path=path,
            content_digest="a" * 64, request_id="req-" + key, nonce="nonce-" + key)

    assert permit(TARGET, "inside-product")["work"] == work
    assert permit(HANDOFF + "/notes.md", "inside-handoff")["work"] == work
    with pytest.raises(MachineTransportError, match="not granted"):
        permit("10.PRODUCT/13.NODE-LANGUAGE/nodelang/universal_application.py", "outside")


def test_an_agent_still_cannot_create_work_and_an_unbound_proposal_grants_nothing(world):
    server, descriptor, provider, browser = world
    proposer, _me = _tools(descriptor, provider, "court-proposer-2")
    agent, _session = _agent(descriptor, provider, "court-direct")
    proposal = _propose(proposer, "Never bound")
    before = server.universal_store.revision
    with pytest.raises(MachineTransportError, match="created by the application owner"):
        agent.request("POST", "/api/universal/work", {
            "title": "Self-created", "description": "no founder", "priority": 1,
            "external_key": "proposal:" + proposal["message_id"], "references": {},
            "structured_references": {"cde-container": work_proposals.cde_container({
                **{key: None for key in ("title", "description", "priority", "purpose", "inputs",
                                         "requirements")}, "container": CONTAINER, "write_grants": GRANTS})},
            "x": 1, "y": 1})
    assert server.universal_store.revision == before
    # No Work exists for the proposal, so its grants admit no write.
    with pytest.raises(MachineTransportError, match="one claimed governed Work|" + GATE):
        agent.issue_cde_write_permit(operation="apply_patch", path=TARGET, content_digest="b" * 64,
                                     request_id="req-unbound", nonce="nonce-unbound")
    # Only the founder binds: an agent's own browser-less call has no founder binding.
    with pytest.raises(Exception):
        work_proposals.bind_work_proposals(server, type("Agent", (), {"subject_root": "not-the-founder"})(),
            {"action": "bind_work_proposals", "root": "r", "scope": "s", "request_id": "x",
             "data_class": "public-text", "proposals": [{"message_id": proposal["message_id"],
             "sequence": proposal["sequence"], "digest": proposal["digest"]}]},
            read_message=lambda sequence: {}, browser_guard=lambda: None)
    assert _proposal_works(server) == set()

def test_the_founders_list_reads_which_proposals_are_already_bound(world):
    """The founder's list asks only the bound state; a bound proposal is never offered again."""
    server, descriptor, provider, browser = world
    proposer, _me = _tools(descriptor, provider, "court-proposer-3")
    first, second = _propose(proposer, "Listed A"), _propose(proposer, "Listed B")
    registry = server.universal_registry
    request = {"action": "read_work_proposals", "root": registry.workshop_root,
               "scope": registry.workshop_workbench_root, "request_id": "court-read", "data_class": "public-text",
               "message_ids": [first["message_id"], second["message_id"]]}

    def listed(body=request):
        with _as_browser(browser):
            return work_proposals.founder_bind_route(server, browser, body, server.browser_session_token)

    before = server.universal_store.revision
    assert listed()["bound"] == {first["message_id"]: None, second["message_id"]: None}
    assert server.universal_store.revision == before              # reading writes nothing
    work = _bind(server, browser, first)["bound"][0]["work_root"]
    assert listed()["bound"] == {first["message_id"]: work, second["message_id"]: None}
    with pytest.raises(InvalidCell, match="exact request"):
        listed({**request, "proposals": []})
    with pytest.raises(InvalidCell, match="distinct proposal messages"):
        listed({**request, "message_ids": [first["message_id"], first["message_id"]]})
    with pytest.raises(Exception, match="Only the founder"):
        work_proposals.read_work_proposals(server, type("Agent", (), {"subject_root": "not-the-founder"})(), request)


def test_the_founder_declines_a_proposal_with_a_persisted_graph_record(world):
    """Reject is a durable founder decision; the declined proposal stops appearing as pending."""
    server, descriptor, provider, browser = world
    proposer, _me = _tools(descriptor, provider, "court-proposer-decline")
    first, second = _propose(proposer, "Declined A"), _propose(proposer, "Still pending")
    registry = server.universal_registry
    request = {"action": "read_work_proposals", "root": registry.workshop_root,
               "scope": registry.workshop_workbench_root, "request_id": "court-read-decline",
               "data_class": "public-text", "message_ids": [first["message_id"], second["message_id"]]}

    declined = _decline(server, browser, first)["declined"][0]
    assert declined["message_id"] == first["message_id"]
    assert declined["state"] == "declined"
    assert declined["actor"] == browser.subject_root
    assert work_proposals._declined_proposals(server.universal_store.snapshot(), registry)[first["message_id"]]["state"] == "declined"

    with _as_browser(browser):
        listed = work_proposals.founder_bind_route(server, browser, request, server.browser_session_token)
    assert listed["bound"] == {first["message_id"]: None, second["message_id"]: None}
    assert listed["declined"][first["message_id"]]["state"] == "declined"
    assert listed["declined"][second["message_id"]] is None
    with pytest.raises(InvalidCell, match="already declined"):
        _bind(server, browser, first)
    with pytest.raises(InvalidCell, match="already declined"):
        _decline(server, browser, first)
    with pytest.raises(InvalidCell, match="changed since it was shown"):
        _decline(server, browser, second, tamper=True)


def test_reject_winning_the_approve_race_creates_no_work(world):
    """Approve rechecks the proposal under the creation lock after validation."""
    server, descriptor, provider, browser = world
    proposer, _me = _tools(descriptor, provider, "court-proposer-race")
    proposal = _propose(proposer, "Race proposal")

    def reject_first():
        _decline(server, browser, proposal)

    before = server.universal_store.revision
    work_proposals._AFTER_PROPOSAL_VALIDATION_HOOK = reject_first
    try:
        with pytest.raises(InvalidCell, match="already declined"):
            _bind(server, browser, proposal)
    finally:
        work_proposals._AFTER_PROPOSAL_VALIDATION_HOOK = None

    assert server.universal_store.revision > before
    assert work_proposals.KEY_PREFIX + proposal["message_id"] not in _proposal_works(server)
    declined = work_proposals._declined_proposals(server.universal_store.snapshot(),
                                                  server.universal_registry)
    assert declined[proposal["message_id"]]["state"] == "declined"


def test_baboom_context_counts_unbound_work_proposals_waiting_for_founder(world):
    """BABOOM reports the real founder approval count from the Workshop tail."""
    from tests_replica.test_application_machine_transport import _FounderLocalClient

    server, descriptor, provider, browser = world
    proposer, _me = _tools(descriptor, provider, "court-baboom-approvals")
    note_writer, _note_session = _agent(descriptor, provider, "court-baboom-note")
    first = _propose(proposer, "BABOOM approval A")
    second = _propose(proposer, "BABOOM approval B")
    _post(note_writer, "plan", [], [], "ordinary-note")
    _bind(server, browser, first)

    client = _FounderLocalClient(server, descriptor, provider)
    client.request("GET", "/api/universal/baboom-context")
    deadline = time.time() + 2.0
    while True:
        context = client.request("GET", "/api/universal/baboom-context")
        if context["workshop"].get("pending_founder_approvals") == 1:
            break
        if time.time() >= deadline:
            pytest.fail("BABOOM approval count cache did not refresh")
        time.sleep(0.02)

    assert context["workshop"]["pending_founder_approvals"] == 1
    line, offer = baboom_face_line(context, None)
    assert line.startswith("1 thing needs your approval in Workshop.")
    assert offer == "open Workshop approvals"
    assert work_proposals.KEY_PREFIX + second["message_id"] not in _proposal_works(server)


def test_baboom_native_frame_reads_cached_pending_approvals_without_frame_count(world, monkeypatch):
    """The native frame omits a cold count, then reports the cached real count."""
    from tests_replica.test_application_machine_transport import _FounderLocalClient

    server, descriptor, provider, _browser = world
    proposer, _me = _tools(descriptor, provider, "court-baboom-native-approvals")
    _propose(proposer, "BABOOM native approval A")
    original = server.conversation_content.project_for_founder_context
    count_reader_threads = []

    def counting_reader(*args, **kwargs):
        if kwargs.get("limit") == 500:
            count_reader_threads.append(threading.current_thread().name)
        return original(*args, **kwargs)

    monkeypatch.setattr(
        server.conversation_content,
        "project_for_founder_context",
        counting_reader,
    )
    client = _FounderLocalClient(server, descriptor, provider)

    cold = client.baboom_native_frame(response_timeout_seconds=60)
    assert "pending_founder_approvals" not in cold["context"]["workshop"]
    assert "MainThread" not in count_reader_threads

    deadline = time.time() + 2.0
    while True:
        frame = client.baboom_native_frame(response_timeout_seconds=60)
        if frame["context"]["workshop"].get("pending_founder_approvals") == 1:
            break
        if time.time() >= deadline:
            pytest.fail("BABOOM native frame did not receive cached approval count")
        time.sleep(0.02)
    assert all(name == "archhub-baboom-pending-approvals" for name in count_reader_threads)
