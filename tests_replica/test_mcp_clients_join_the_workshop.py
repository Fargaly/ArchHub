"""Spark, Notion and any other MCP client the founder connects join his Workshop as
their OWN agents, the way Claude and Codex do (founder order 2026-09-30).

The cloud queues one Workshop step as a workshop-call task naming the OAuth client;
the founder's running app (nodelang/cloud_relay.py) binds that client as a runtime
Agent Session (runtime mcp-<name>, external session mcp:<client_id>) and runs the
step through InstalledWorkshopCoordinationClient -- the same allowlisted methods the
local coordination MCP gives Claude and Codex. These courts run it against the real
application server: two clients are two agents, one can message the other, nothing
outside the allowlist runs, and a relay without the caller never claims the kind.

Run: python -m pytest tests_replica/test_mcp_clients_join_the_workshop.py -q
"""
import json

import pytest

from nodelang import commit_intent
from nodelang.cloud_relay import CloudRelay, McpWorkshopAgents, WORKSHOP_CALL, mcp_runtime
from nodelang.universal_application import set_universal_scope
from tests_replica.test_cloud_relay_host_read import _Cloud, cloud  # noqa: F401  (fixture)
from tests_replica.test_workshop_execution_gate import _serve

SPARK = {"client_id": "spark-client-7f3c", "client_name": "Gemini Spark"}
NOTION = {"client_id": "notion-client-19ab", "client_name": "Notion"}


@pytest.fixture
def served(tmp_path, monkeypatch):
    server, descriptor, provider = _serve("content-store", tmp_path, monkeypatch)
    binding = server._resolve_browser_session(server.browser_session_token)
    with server.mutation_lock, commit_intent.declare(commit_intent.USER_ACTION, actor="court", reason="scope"):
        set_universal_scope(server.universal_store, server.universal_registry, authentication_context=binding.context)
    try:
        yield server, descriptor, provider
    finally:
        server.close()


def test_every_mcp_client_runs_under_its_own_mcp_runtime():
    assert mcp_runtime("Gemini Spark") == "mcp-gemini-spark"
    assert mcp_runtime("Notion") == "mcp-notion"
    # A client naming itself after a native agent never lands in that agent's body.
    assert mcp_runtime("Claude") == "mcp-claude" and mcp_runtime("codex") == "mcp-codex"
    assert mcp_runtime("") == "mcp-client" and mcp_runtime("!!!") == "mcp-client"


def test_two_clients_are_two_agents_and_one_messages_the_other(served):
    server, descriptor, provider = served
    agents = McpWorkshopAgents(descriptor, provider)
    spark = agents.call(SPARK, "workshop_lens", {})
    notion = agents.call(NOTION, "workshop_lens", {})
    assert spark["ok"] is True and notion["ok"] is True
    assert spark["agent_runtime"] == "mcp-gemini-spark" and notion["agent_runtime"] == "mcp-notion"
    assert spark["self"].startswith("app:agent-session:runtime:")
    assert spark["self"] != notion["self"], "each client is its own agent"
    # The same client keeps its one agent across steps.
    assert agents.call(SPARK, "list_agents", {})["self"] == spark["self"]

    sent = agents.call(SPARK, "send_message", {
        "target": notion["self"], "message": "Spark to Notion: court handshake",
        "idempotency_key": "court-spark-handshake-1"})
    assert sent["actor"] == spark["self"] and sent["recipients"] == [notion["self"]]
    again = agents.call(SPARK, "send_message", {
        "target": notion["self"], "message": "Spark to Notion: court handshake",
        "idempotency_key": "court-spark-handshake-1"})
    assert again["message_id"] == sent["message_id"], "a retried post is the same message"

    page = agents.call(NOTION, "read_messages", {"limit": 10})
    seen = [entry for entry in page["entries"] if entry["message_id"] == sent["message_id"]]
    assert len(seen) == 1 and seen[0]["actor"] == spark["self"]
    acked = agents.call(NOTION, "acknowledge_message", {
        "message_id": sent["message_id"], "sequence": seen[0]["sequence"],
        "idempotency_key": "court-notion-ack-1"})
    assert acked["actor"] == notion["self"] and acked["recipients"] == [spark["self"]]


@pytest.mark.parametrize("method", ["run_workshop_task", "execute_workshop_task", "attach_agent",
                                    "register_session_as", "", None])
def test_nothing_outside_the_workshop_allowlist_runs_and_nothing_is_enrolled(served, method):
    server, descriptor, provider = served
    enrolled = []
    agents = McpWorkshopAgents(descriptor, provider, client_factory=lambda: enrolled.append(1))
    before = server.universal_store.revision
    with pytest.raises(PermissionError, match="not a Workshop step"):
        agents.call(SPARK, method, {})
    assert enrolled == [] and server.universal_store.revision == before


@pytest.mark.parametrize("agent", [None, {}, {"client_id": ""}, {"client_id": "a b"},
                                   {"client_id": "x" * 201}, "spark"])
def test_a_step_without_a_proper_client_id_is_refused_before_any_binding(served, agent):
    _server, descriptor, provider = served
    enrolled = []
    agents = McpWorkshopAgents(descriptor, provider, client_factory=lambda: enrolled.append(1))
    with pytest.raises(ValueError):
        agents.call(agent, "workshop_lens", {})
    assert enrolled == []


def _relay(base, caller):
    return CloudRelay(base_url=base, token="t", respond=lambda u: {}, execute=lambda u: {},
                      hosts=lambda: [], workshop_caller=caller)


def test_the_relay_claims_workshop_steps_only_when_it_can_answer_them(cloud):  # noqa: F811
    _relay(cloud, None).poll_once()
    assert WORKSHOP_CALL not in _Cloud.claims[-1]["kinds"]
    _relay(cloud, lambda *a: {}).poll_once()
    assert WORKSHOP_CALL in _Cloud.claims[-1]["kinds"]


def test_the_relay_answers_a_workshop_step_through_the_caller_and_never_baboom(cloud):  # noqa: F811
    seen, baboom = [], []
    relay = CloudRelay(base_url=cloud, token="t",
                       respond=lambda u: baboom.append(u) or {}, execute=lambda u: baboom.append(u) or {},
                       hosts=lambda: [],
                       workshop_caller=lambda agent, method, params: seen.append((agent, method, params))
                       or {"ok": True, "self": "app:agent-session:runtime:" + "a" * 32})
    step = {"agent": SPARK, "method": "read_messages", "params": {"limit": 5}}
    _Cloud.tasks[:] = [{"id": "w1", "kind": WORKSHOP_CALL, "directive": json.dumps(step)}]
    answered = relay.poll_once()
    assert answered["ok"] is True and baboom == []
    assert seen == [(SPARK, "read_messages", {"limit": 5})]
    assert json.loads(_Cloud.results[-1]["result"])["self"].startswith("app:agent-session:runtime:")
    _Cloud.tasks[:] = [{"id": "w2", "kind": WORKSHOP_CALL, "directive": "not json"}]
    refused = relay.poll_once()
    assert refused["ok"] is False and _Cloud.results[-1]["ok"] is False and baboom == []


def test_the_launcher_wires_the_workshop_caller_and_a_failure_never_stops_the_relay(monkeypatch, tmp_path):
    """The actual launcher block: with its runtime names present the relay gets
    McpWorkshopAgents.call; without them (the caller cannot be built) the relay
    still starts, with Workshop steps refused."""
    from tests_replica import test_baboom_startup_lifecycle as names_court
    from tests_replica import test_the_cockpit_outlives_baboom as launcher_court
    from nodelang import cloud_relay
    from nodelang.cell_secret_keys import MemorySigningKeyProvider
    original = names_court.launcher_names

    def with_runtime(*names, **values):
        return original(*names, **values, descriptor_path=tmp_path / "runtime-descriptor.json",
                        machine_key_provider=MemorySigningKeyProvider("archhub.local.universal-runtime-pipe", b"m" * 32))

    monkeypatch.setattr(names_court, "launcher_names", with_runtime)
    _ns, relay = launcher_court._start_actual_relay_block(monkeypatch)
    assert getattr(relay.workshop_caller, "__self__", None).__class__ is cloud_relay.McpWorkshopAgents
    monkeypatch.setattr(names_court, "launcher_names", original)
    _ns, relay = launcher_court._start_actual_relay_block(monkeypatch)
    assert relay.workshop_caller is None
