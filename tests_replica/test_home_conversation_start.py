"""Home starts real indexed conversations; only the provider response is a fixture."""
import json
from io import BytesIO
from pathlib import Path
import secrets
import time
import pytest
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import urlencode

from nodelang.application_server import ApplicationServer
from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang import agent_composer, model_router, universal_application as app, universal_pipeline
from nodelang.universal_cell import InvalidCell


def test_home_prompt_model_reply_persist_in_one_conversation_without_replay(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHHUB_GRAND_MAP_PATH", str(Path(app.__file__).parent / "data/public_runtime_map.json"))
    keys = MemorySigningKeyProvider("archhub.local.relationship-authority", secrets.token_bytes(32))
    keys.add_key("archhub.local.court-attestation", secrets.token_bytes(32))
    database = tmp_path / "fresh-home.sqlite3"
    calls = []
    provider_contexts = []

    key_available = False
    move_scope_before_dispatch = False

    def provider(request, timeout):
        assert not server.mutation_lock._is_owned()
        payload = json.loads(request.data)
        prompt = payload["messages"][-1]["content"].rsplit("FOUNDER: ", 1)[1]
        model = payload["model"]
        calls.append((prompt, model))
        provider_contexts.append(payload["messages"][-1]["content"].rsplit("FOUNDER: ", 1)[0])
        if prompt == "Exercise an unknown provider outcome":
            raise URLError("Private provider failure detail")
        actions = [{"op":"select", "roots":[node]}] if prompt == "Refer to the explanation you just gave me" else []
        content = json.dumps({"actions":actions, "answer":"The provider fixture answered the saved prompt."})
        return BytesIO(json.dumps({"choices":[{"message":{"content":content}}]}).encode())

    def routed(*args, **kwargs):
        def key_input(name):
            if move_scope_before_dispatch:
                with server.mutation_lock:
                    browser = server._resolve_browser_session(server.browser_session_token)
                    app.set_universal_scope(server.universal_store, server.universal_registry,
                        server.universal_registry.canvas_root, authentication_context=browser.context)
            return "synthetic-fixture-key" if key_available else ""
        return model_router.route_chat(*args, **kwargs, opener=provider, environ={},
            secrets_loader=key_input, cloud_session=None)
    monkeypatch.setattr(agent_composer, "route_chat", routed)

    def start():
        return ApplicationServer(universal_state_path=database, universal_key_provider=keys,
            universal_workspace_root=tmp_path, enable_machine_transport=False,
            enable_universal_cloud_gateway=False, enable_machine_projection_prewarm=False,
            live_watch=False).start()

    def request(path, body=None, expected=200):
        call = Request(server.url + path, headers={"Content-Type":"application/json", "Origin":server.url,
            "Cookie":"ArchHub-Session=" + server.browser_session_token,
            "X-ArchHub-CSRF":server.browser_csrf_token},
            data=None if body is None else json.dumps(body).encode())
        try:
            with urlopen(call, timeout=40) as response:
                status, result = response.status, json.loads(response.read())
        except HTTPError as exc:
            status, result = exc.code, json.loads(exc.read())
        assert status == expected, result
        return result

    body = {"action":"start-session", "prompt":"What can I create in this graph? Please explain the available next step without executing any workflow.",
        "model":"openrouter/free", "idempotency_key":"home-user-request-one"}
    server = start()
    try:
        missing = request("/api/universal/workshop", body)
        assert missing["delivery"]["state"] == "not_sent" and missing["delivery"]["provider_not_called"]
        assert "No OpenRouter key" in missing["delivery"]["message"] and not calls
        key_available = True
        result = request("/api/universal/workshop", body)
        assert result["root"] == missing["root"] and result["message_id"] == missing["message_id"]
        assert result["delivery"]["node"] == missing["delivery"]["node"]
        assert result["delivery"]["state"] == "replied", result
        assert calls == [(body["prompt"], body["model"])]
        conversation = result["root"]
        node = result["delivery"]["node"]
        registry = server.universal_registry
        assert conversation != registry.workshop_root
        assert result["scope_path"] == [registry.map.domains["brain"], registry.workshop_workbench_root]
        canvas = request("/api/universal/canvas")
        assert node in {row["id"] for row in canvas["nodes"]}
        model = next(row for row in canvas["properties"] if row["owner"] == node and row["label"] == "model")
        assert model["value"] == body["model"] and model["editable"] is True
        query = urlencode({"root":conversation, "scope":registry.workshop_workbench_root})
        page = request("/api/universal/workshop?" + query)
        assert body["prompt"] in str(page)
        assert "The provider fixture answered the saved prompt." in str(page)
        assert page["model_agent"] == result["model_agent"]
        followup = {"action":"send-model", "root":conversation, "scope":result["scope"], "node":node,
            "binding_digest":page["model_agent"]["binding_digest"],
            "prompt":"Refer to the explanation you just gave me", "idempotency_key":"model-followup-one"}
        continued = request("/api/universal/workshop", followup)
        assert continued["delivery"]["state"] == "replied" and continued["root"] == conversation
        assert continued["node"] == node and continued["binding_digest"] == followup["binding_digest"]
        assert continued["scope"] == result["scope"] and continued["graph_id"] == result["graph_id"]
        assert len(calls) == 2 and calls[-1][0] == followup["prompt"]
        assert body["prompt"] in provider_contexts[-1]
        assert "The provider fixture answered the saved prompt." in provider_contexts[-1]
        assert "Session request " not in provider_contexts[-1]
        assert "The agent request started." not in provider_contexts[-1]
        same_followup = request("/api/universal/workshop", followup)
        assert same_followup["message_id"] == continued["message_id"] and len(calls) == 2
        request("/api/universal/workshop", {**followup, "prompt":"Changed follow-up"}, expected=400)
        latest = request("/api/universal/workshop?" + query)
        assert "Draft prepared for your review" in str(latest) and "select: prepared" in str(latest)
        browser = server._resolve_browser_session(server.browser_session_token)
        with server.mutation_lock:
            app.edit_universal_property(server.universal_store, registry, model["relation"], "ollama/changed-fixture",
                authentication_context=browser.context)
        changed = request("/api/universal/workshop?" + query + "&content_after=" + latest["content_cursor"])
        assert changed["unchanged"] is True and changed["model_agent"]["model"] == "ollama/changed-fixture"
        assert changed["model_agent"]["binding_digest"] != followup["binding_digest"]
        request("/api/universal/workshop", {**followup, "idempotency_key":"stale-model-binding"}, expected=400)
        assert len(calls) == 2
        with server.mutation_lock:
            app.edit_universal_property(server.universal_store, registry, model["relation"], body["model"],
                authentication_context=browser.context)
            app.set_universal_selection(server.universal_store, registry, [],
                authentication_context=browser.context)
            prior_revision = server.universal_store.revision
            with pytest.raises(InvalidCell, match="parameters changed"):
                universal_pipeline.create_engine_node(server.universal_store, registry, title="Refused replacement",
                    engine="library.think", properties={"model":"ollama/conflict", "conversation":conversation},
                    instance_token=node.removeprefix("assembly-instance:"), authentication_context=browser.context)
            assert server.universal_store.revision == prior_revision
        repeated = request("/api/universal/workshop", body)
        assert repeated["root"] == conversation and repeated["message_id"] == result["message_id"]
        assert len(calls) == 2
        request("/api/universal/graph-open", {"root":registry.canvas_root})
        before_refusal = request("/api/universal/canvas")
        request("/api/universal/workshop", {**body, "prompt":body["prompt"] + " Changed intent."}, expected=400)
        after_refusal = request("/api/universal/canvas")
        assert after_refusal["scope"] == before_refusal["scope"]
        assert after_refusal["revision"] == before_refusal["revision"]
        request("/api/universal/workshop", {**body, "model":"ollama/another"}, expected=400)
        assert len(calls) == 2
        failed_body = {**body, "prompt":"Exercise an unknown provider outcome",
            "idempotency_key":"home-unknown-outcome"}
        failed = request("/api/universal/workshop", failed_body)
        assert failed["delivery"]["state"] == "failed" and len(calls) == 3

        real_place = universal_pipeline.create_engine_node
        partial_nodes = []
        def interrupted_place(*args, **kwargs):
            placed = real_place(*args, **kwargs)
            partial_nodes.append(placed["root"])
            raise RuntimeError("Fixture interruption after atomic node placement")
        monkeypatch.setattr(universal_pipeline, "create_engine_node", interrupted_place)
        partial_body = {**body, "prompt":"Resume my interrupted first message", "idempotency_key":"home-partial-node"}
        request("/api/universal/workshop", partial_body, expected=400)
        held_nodes = {row["id"] for row in request("/api/universal/canvas")["nodes"]}
        monkeypatch.setattr(universal_pipeline, "create_engine_node", real_place)
        resumed = request("/api/universal/workshop", partial_body)
        assert resumed["delivery"]["node"] == partial_nodes[0]
        assert {row["id"] for row in request("/api/universal/canvas")["nodes"]} == held_nodes
        assert len(calls) == 4
    finally:
        server.close()

    server = start()
    try:
        repeated = request("/api/universal/workshop", body)
        assert repeated["root"] == conversation and repeated["message_id"] == result["message_id"]
        assert repeated["delivery"]["state"] == "replied"
        assert len(calls) == 4
        assert "The provider fixture answered the saved prompt." in str(request("/api/universal/workshop?" + query))

        failed_retry = request("/api/universal/workshop", failed_body)
        assert failed_retry["root"] == failed["root"]
        assert failed_retry["delivery"]["state"] == "already_recorded" and len(calls) == 4
        failed_page = request("/api/universal/workshop?" + urlencode({
            "root":failed["root"], "scope":failed["scope"]}))
        assert failed_body["prompt"] in str(failed_page)
        assert "Private provider failure detail" not in str(failed_page)

        # Reuse the native owner's named external-transport fixture. All graph,
        # browser admission, relay scheduling and indexed history stay real.
        from tests_replica.test_native_contact import Transport
        transport = Transport()
        server.native_recipient_relay._transport = transport
        native_body = {"action":"start-session", "prompt":"Send this exact first native message",
            "native":{"app":"claude", "session_id":"existing-external"},
            "idempotency_key":"home-native-one"}
        native = request("/api/universal/workshop", native_body)
        assert native["delivery"]["state"] == "started", native
        assert native["contact"] == native["delivery"]["contact"]
        deadline = time.monotonic() + 3
        while server.native_recipient_relay._pending_jobs and time.monotonic() < deadline:
            time.sleep(.01)
        assert server.native_recipient_relay.last_error is None
        assert len(transport.calls) == 1 and not server._machine_agent_sessions
        native_page = request("/api/universal/workshop?" + urlencode({
            "root":native["root"], "scope":native["scope"]}))
        assert native_body["prompt"] in str(native_page) and "Fixture reply" in str(native_page)
        native_retry = request("/api/universal/workshop", native_body)
        assert native_retry["root"] == native["root"] and native_retry["message_id"] == native["message_id"]
        assert len(transport.calls) == 1
        assert native["root"] not in {conversation, failed["root"], server.universal_registry.workshop_root}

        # A real scope change during key lookup makes the Agent invisible at the
        # actual router boundary; no provider request or dispatch receipt occurs.
        move_scope_before_dispatch = True
        raced = request("/api/universal/workshop", {**body, "idempotency_key":"scope-race-home"})
        assert raced["delivery"]["state"] == "not_sent"
        assert raced["delivery"]["provider_not_called"] and "not visible" in raced["delivery"]["message"]
        assert len(calls) == 4 and len(transport.calls) == 1
    finally:
        server.close()
