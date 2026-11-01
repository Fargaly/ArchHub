"""Remote OAuth Work claims retain their existing independent authorization.

Generic peer messaging uses the shared send/read connector; retired cloud chat
methods must refuse before obtaining a Work actor. Queue, consent, caller identity
and no-enrollment assertions remain.
"""
import json

import pytest

from nodelang import commit_intent
from nodelang.cloud_relay import CloudRelay, McpWorkshopAgents, WORKSHOP_CALL, mcp_runtime
from nodelang.universal_application import set_universal_scope
from tests_replica.test_cloud_relay_host_read import _Cloud, cloud  # noqa: F401  (fixture)
from tests_replica.test_workshop_execution_gate import _serve

SPARK = {"client_id": "spark-client-7f3c", "client_name": "Gemini Spark"}


@pytest.fixture(scope="module")
def served(tmp_path_factory):
    """All remaining parameterized callers are read-only refusals; share one real owner.

    Every original before/after revision and no-enrollment assertion still runs.
    """
    with pytest.MonkeyPatch.context() as monkeypatch:
        tmp_path = tmp_path_factory.mktemp("remote-work-claims")
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




@pytest.mark.parametrize("method", ["run_workshop_task", "execute_workshop_task", "attach_agent",
                                    "register_session_as", "", None, "read_message",
                                    "acknowledge_message", "list_agents", "workshop_lens"])
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
        agents.call(agent, "claim_work", {})
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
    step = {"agent": SPARK, "method": "claim_work", "params": {"work_root": "assembly-instance:court"}}
    _Cloud.tasks[:] = [{"id": "w1", "kind": WORKSHOP_CALL, "directive": json.dumps(step)}]
    answered = relay.poll_once()
    assert answered["ok"] is True and baboom == []
    assert seen == [(SPARK, "claim_work", {"work_root": "assembly-instance:court"})]
    assert json.loads(_Cloud.results[-1]["result"])["self"].startswith("app:agent-session:runtime:")
    _Cloud.tasks[:] = [{"id": "w2", "kind": WORKSHOP_CALL, "directive": "not json"}]
    refused = relay.poll_once()
    assert refused["ok"] is False and _Cloud.results[-1]["ok"] is False and baboom == []


def test_nograph_wires_the_workshop_caller_and_a_failure_never_stops_the_app(monkeypatch, tmp_path):
    """The running app is the file server. It claims gated effects and Workshop
    steps; if the relay cannot start, the app still comes up."""
    import threading
    from types import SimpleNamespace
    from nodelang.cloud_relay import HOST_EFFECT, HOST_READ, McpWorkshopAgents
    from nodelang.nograph_server import NoGraphServer

    starts = []

    def start(**kwargs):
        relay = SimpleNamespace(**kwargs, _stop=threading.Event())
        starts.append(relay)
        return relay

    monkeypatch.setattr("nodelang.cloud_relay.start_cloud_relay", start)
    server = SimpleNamespace(_relay_lock=threading.Lock(), cloud_relay=None, state_dir=tmp_path)
    relay = NoGraphServer.ensure_cloud_relay(server)
    assert relay is starts[0]
    assert isinstance(getattr(relay.workshop_caller, "__self__", None), McpWorkshopAgents)
    assert relay.app_kinds == (HOST_READ, HOST_EFFECT)

    def boom(**kwargs):
        raise RuntimeError("no session")

    monkeypatch.setattr("nodelang.cloud_relay.start_cloud_relay", boom)
    server.cloud_relay = None
    assert NoGraphServer.ensure_cloud_relay(server) is None
