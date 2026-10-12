import io
import json
import sys
import hashlib
import secrets
import threading
import time
import urllib.error
from pathlib import Path
from urllib.parse import urlencode
from urllib.error import HTTPError
from urllib.request import Request, urlopen


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class _Answer(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *unused):
        return False


def test_universal_agent_post_without_node_reaches_router_with_generation(monkeypatch):
    from nodelang import agent_composer, application_server, universal_application

    class Store:
        revision = 7

    body = {
        "prompt": "Reply with the single word PONG.",
        "model": "fake/model",
        "generation": {"temperature": 0.2, "top_p": 0.8, "max_tokens": 16},
    }
    captured = {}

    monkeypatch.setattr(
        universal_application,
        "project_universal_canvas",
        lambda *args, **kwargs: {"scope": {"current": "scope-a"}, "nodes": [], "catalog": [], "properties": []},
    )

    def fake_chat(prompt, context_block, model, **kwargs):
        captured.update({"prompt": prompt, "model": model, **kwargs})
        return '{"actions":[],"answer":"PONG"}'

    monkeypatch.setattr(agent_composer, "_chat", fake_chat)

    result = agent_composer.run_agent_composer(
        Store(),
        object(),
        body["prompt"],
        model=body["model"],
        generation=body["generation"],
        **application_server._agent_node_request_kwargs(body),
    )

    assert result["answer"] == "PONG"
    assert captured["model"] == "fake/model"
    assert captured["generation"] == body["generation"]
    assert application_server._agent_node_request_kwargs({**body, "node": None}) == {}
    assert application_server._agent_node_request_kwargs({**body, "node": ""}) == {}


def test_node_agent_turn_survives_reopen_without_replay(tmp_path, monkeypatch):
    from nodelang import (
        agent_composer, application_server, commit_intent, pipeline_engines,
        universal_application,
    )
    from nodelang.cell_secret_keys import MemorySigningKeyProvider
    from nodelang.universal_pipeline import create_engine_node

    monkeypatch.setenv("ARCHHUB_GRAND_MAP_PATH",
        str(Path(universal_application.__file__).parent / "data" / "public_runtime_map.json"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
    monkeypatch.setattr(pipeline_engines, "brain_recall", lambda params, feeds: ({"out": ""}, ""))
    calls = []

    def fake_chat(prompt, context_block, model, **kwargs):
        calls.append({"prompt": prompt, "context": context_block, "model": model})
        return json.dumps({"actions": [], "answer": "Node answer one."})

    monkeypatch.setattr(agent_composer, "_chat", fake_chat)

    keys = MemorySigningKeyProvider("archhub.local.relationship-authority", secrets.token_bytes(32))
    keys.add_key("archhub.local.court-attestation", secrets.token_bytes(32))
    state = tmp_path / "app.sqlite3"
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    def start():
        return application_server.ApplicationServer(universal_state_path=state,
            universal_key_provider=keys, universal_workspace_root=workspace,
            enable_machine_transport=False, enable_universal_cloud_gateway=False,
            enable_machine_projection_prewarm=False, live_watch=False).start()

    def request(server, path, body=None):
        call = Request(server.url + path, headers={"Content-Type": "application/json",
            "Origin": server.url, "Cookie": "ArchHub-Session=" + server.browser_session_token,
            "X-ArchHub-Session": server.browser_session_token,
            "X-ArchHub-CSRF": server.browser_csrf_token},
            data=None if body is None else json.dumps(body).encode())
        try:
            with urlopen(call, timeout=120) as response:
                return json.loads(response.read())
        except HTTPError as exc:
            raise AssertionError(json.loads(exc.read())) from exc

    first = start()
    try:
        browser = first._resolve_browser_session(first.browser_session_token)
        with first.mutation_lock:
            with commit_intent.declare(commit_intent.USER_ACTION, actor="court",
                                       reason="the user places a node-chat fixture"):
                node = create_engine_node(first.universal_store, first.universal_registry,
                    title="Node chat", engine="library.think", properties={"model": "court/free"},
                    authentication_context=browser.context)["root"]
        sent = request(first, "/api/universal/agent",
            {"prompt": "remember this node turn", "model": "court/free", "node": node,
             "request_id": "n-reopen-1"})
        assert sent["answer"] == "Node answer one."
        scope = request(first, "/api/universal/canvas")["scope"]["current"]
    finally:
        first.close()

    reopened = start()
    try:
        read = request(reopened, "/api/universal/workshop-transcript?" + urlencode(
            {"node": node, "scope": scope}))
        assert read["conversation_root"]
        assert [(row["kind"], row["text"]) for row in read["rows"]] == [
            ("message", "remember this node turn"),
            ("reply", "Node answer one."),
        ]
        assert sent["delivery"]["state"] == "replied"
        assert (sent["delivery"]["message_id"], sent["delivery"]["reply_message_id"]) == (
            read["rows"][0]["id"], read["rows"][1]["id"]), "the first send names the rows the transcript holds"
        assert len(calls) == 1
    finally:
        reopened.close()


def test_graph_agent_turn_survives_reopen_and_retry_without_replay(tmp_path, monkeypatch):
    from nodelang import (
        agent_composer, application_server, pipeline_engines, universal_application,
    )
    from nodelang.cell_secret_keys import MemorySigningKeyProvider

    monkeypatch.setenv("ARCHHUB_GRAND_MAP_PATH",
        str(Path(universal_application.__file__).parent / "data" / "public_runtime_map.json"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
    monkeypatch.setattr(pipeline_engines, "brain_recall", lambda params, feeds: ({"out": ""}, ""))
    calls = []

    def fake_chat(prompt, context_block, model, **kwargs):
        calls.append({"prompt": prompt, "model": model})
        return json.dumps({"actions": [], "answer": "Graph answer one."})

    monkeypatch.setattr(agent_composer, "_chat", fake_chat)
    keys = MemorySigningKeyProvider("archhub.local.relationship-authority", secrets.token_bytes(32))
    keys.add_key("archhub.local.court-attestation", secrets.token_bytes(32))
    state = tmp_path / "app.sqlite3"
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    def start():
        return application_server.ApplicationServer(universal_state_path=state,
            universal_key_provider=keys, universal_workspace_root=workspace,
            enable_machine_transport=False, enable_universal_cloud_gateway=False,
            enable_machine_projection_prewarm=False, live_watch=False).start()

    def request(server, path, body=None):
        call = Request(server.url + path, headers={"Content-Type": "application/json",
            "Origin": server.url, "Cookie": "ArchHub-Session=" + server.browser_session_token,
            "X-ArchHub-Session": server.browser_session_token,
            "X-ArchHub-CSRF": server.browser_csrf_token},
            data=None if body is None else json.dumps(body).encode())
        try:
            with urlopen(call, timeout=120) as response:
                return json.loads(response.read())
        except HTTPError as exc:
            raise AssertionError(json.loads(exc.read())) from exc

    first = start()
    try:
        scope = request(first, "/api/universal/canvas")["scope"]["current"]
        body = {"prompt": "remember this graph turn", "model": "court/free",
            "graph": True, "graph_id": scope, "request_id": "g1"}
        sent = request(first, "/api/universal/agent", body)
        assert sent["answer"] == "Graph answer one."
        # UX-CHAT1 v3: the first send names the question and reply rows it wrote (the UI reconciles by them).
        first_read = request(first, "/api/universal/workshop-transcript?" + urlencode(
            {"node": "graph:" + scope, "scope": scope}))
        assert [row["kind"] for row in first_read["rows"]] == ["message", "reply"]
        assert sent["delivery"] == {"state": "replied", "request_id": "g1",
            "message_id": first_read["rows"][0]["id"], "reply_message_id": first_read["rows"][1]["id"]}
    finally:
        first.close()

    reopened = start()
    try:
        read_before_retry = request(reopened, "/api/universal/workshop-transcript?" + urlencode(
            {"node": "graph:" + scope, "scope": scope}))
        assert [(row["kind"], row["text"]) for row in read_before_retry["rows"]] == [
            ("message", "remember this graph turn"),
            ("reply", "Graph answer one."),
        ]
        repeated = request(reopened, "/api/universal/agent", body)
        assert repeated["answer"] == "Graph answer one."
        assert repeated["delivery"] == sent["delivery"], "a replayed send names the same rows as the first send"
        assert len(calls) == 1
        read = request(reopened, "/api/universal/workshop-transcript?" + urlencode(
            {"node": "graph:" + scope, "scope": scope}))
        assert read["conversation_root"] == application_server._agent_graph_conversation_root(
            reopened.universal_registry, scope)
        assert [(row["kind"], row["text"]) for row in read["rows"]] == [
            ("message", "remember this graph turn"),
            ("reply", "Graph answer one."),
        ]
    finally:
        reopened.close()


def test_non_model_canvas_node_agent_turn_uses_picked_model_and_persists(tmp_path, monkeypatch):
    from nodelang import (
        agent_composer, application_server, commit_intent, pipeline_engines,
        universal_application,
    )
    from nodelang.cell_secret_keys import MemorySigningKeyProvider
    from nodelang.universal_pipeline import create_engine_node

    monkeypatch.setenv("ARCHHUB_GRAND_MAP_PATH",
        str(Path(universal_application.__file__).parent / "data" / "public_runtime_map.json"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
    monkeypatch.setattr(pipeline_engines, "brain_recall", lambda params, feeds: ({"out": ""}, ""))
    calls = []

    def fake_chat(prompt, context_block, model, **kwargs):
        calls.append({"prompt": prompt, "model": model})
        return json.dumps({"actions": [], "answer": "Node default model answer."})

    monkeypatch.setattr(agent_composer, "_chat", fake_chat)
    keys = MemorySigningKeyProvider("archhub.local.relationship-authority", secrets.token_bytes(32))
    keys.add_key("archhub.local.court-attestation", secrets.token_bytes(32))
    (tmp_path / "workspace").mkdir()
    server = application_server.ApplicationServer(universal_state_path=tmp_path / "app.sqlite3",
        universal_key_provider=keys, universal_workspace_root=tmp_path / "workspace",
        enable_machine_transport=False, enable_universal_cloud_gateway=False,
        enable_machine_projection_prewarm=False, live_watch=False).start()

    def request(path, body=None):
        call = Request(server.url + path, headers={"Content-Type": "application/json",
            "Origin": server.url, "Cookie": "ArchHub-Session=" + server.browser_session_token,
            "X-ArchHub-Session": server.browser_session_token,
            "X-ArchHub-CSRF": server.browser_csrf_token},
            data=None if body is None else json.dumps(body).encode())
        try:
            with urlopen(call, timeout=120) as response:
                return json.loads(response.read())
        except HTTPError as exc:
            raise AssertionError(json.loads(exc.read())) from exc

    try:
        browser = server._resolve_browser_session(server.browser_session_token)
        with server.mutation_lock:
            with commit_intent.declare(commit_intent.USER_ACTION, actor="court",
                                       reason="the user places a non-model node-chat fixture"):
                node = create_engine_node(server.universal_store, server.universal_registry,
                    title="Line Watcher", engine="lines.watch",
                    authentication_context=browser.context)["root"]
        body = {"prompt": "remember this ordinary node", "model": "court/free",
            "node": node, "request_id": "n2"}
        sent = request("/api/universal/agent", body)
        assert sent["answer"] == "Node default model answer."
        assert calls == [{"prompt": "remember this ordinary node", "model": "court/free"}]
        scope = request("/api/universal/canvas")["scope"]["current"]
        read = request("/api/universal/workshop-transcript?" + urlencode(
            {"node": node, "scope": scope}))
        assert [(row["kind"], row["text"]) for row in read["rows"]] == [
            ("message", "remember this ordinary node"),
            ("reply", "Node default model answer."),
        ]
    finally:
        server.close()


def test_node_agent_retry_after_dispatched_without_reply_does_not_replay(tmp_path, monkeypatch):
    from nodelang import (
        agent_composer, application_server, commit_intent, pipeline_engines,
        universal_application,
    )
    from nodelang.cell_secret_keys import MemorySigningKeyProvider
    from nodelang.universal_pipeline import create_engine_node

    monkeypatch.setenv("ARCHHUB_GRAND_MAP_PATH",
        str(Path(universal_application.__file__).parent / "data" / "public_runtime_map.json"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
    monkeypatch.setattr(pipeline_engines, "brain_recall", lambda params, feeds: ({"out": ""}, ""))
    calls = []

    def fake_chat(prompt, context_block, model, **kwargs):
        calls.append(prompt)
        if kwargs.get("before_dispatch"):
            kwargs["before_dispatch"]()
        raise RuntimeError("fixture response lost after dispatch")

    monkeypatch.setattr(agent_composer, "_chat", fake_chat)

    keys = MemorySigningKeyProvider("archhub.local.relationship-authority", secrets.token_bytes(32))
    keys.add_key("archhub.local.court-attestation", secrets.token_bytes(32))
    (tmp_path / "workspace").mkdir()
    server = application_server.ApplicationServer(universal_state_path=tmp_path / "app.sqlite3",
        universal_key_provider=keys, universal_workspace_root=tmp_path / "workspace",
        enable_machine_transport=False, enable_universal_cloud_gateway=False,
        enable_machine_projection_prewarm=False, live_watch=False).start()

    def request(path, body=None, expected=200):
        call = Request(server.url + path, headers={"Content-Type": "application/json",
            "Origin": server.url, "Cookie": "ArchHub-Session=" + server.browser_session_token,
            "X-ArchHub-Session": server.browser_session_token,
            "X-ArchHub-CSRF": server.browser_csrf_token},
            data=None if body is None else json.dumps(body).encode())
        try:
            with urlopen(call, timeout=120) as response:
                status, result = response.status, json.loads(response.read())
        except HTTPError as exc:
            status, result = exc.code, json.loads(exc.read())
        assert status == expected, result
        return result

    try:
        browser = server._resolve_browser_session(server.browser_session_token)
        with server.mutation_lock:
            with commit_intent.declare(commit_intent.USER_ACTION, actor="court",
                                       reason="the user places a node-chat fixture"):
                node = create_engine_node(server.universal_store, server.universal_registry,
                    title="Retry node", engine="library.think", properties={"model": "court/free"},
                    authentication_context=browser.context)["root"]
        body = {"prompt": "do not replay this", "model": "court/free",
            "node": node, "request_id": "n-retry-1"}
        first = request("/api/universal/agent", body)
        assert first["delivery"]["state"] == "reply_not_confirmed"
        assert first["delivery"]["provider_may_have_been_called"] is True
        assert "provider_not_called" not in first["delivery"]
        second = request("/api/universal/agent", body)
        assert second["delivery"]["state"] == "reply_not_confirmed"
        assert second["delivery"]["provider_may_have_been_called"] is True
        assert second["delivery"]["resent"] is False
        assert "provider_not_called" not in second["delivery"]
        assert calls == ["do not replay this"]
        scope = request("/api/universal/canvas")["scope"]["current"]
        read = request("/api/universal/workshop-transcript?" + urlencode(
            {"node": node, "scope": scope}))
        assert [(row["kind"], row["text"]) for row in read["rows"]] == [
            ("message", "do not replay this"),
        ]
        with server.mutation_lock:
            binding = server.conversation_content._authorize_content_read(
                server.universal_store.snapshot(), server.universal_registry,
                space_root=read["conversation_root"], authentication_context=browser.context,
                principal=browser.subject_root, machine=False)
            history = server.conversation_content._history_for(binding)
            started = history.get_by_idempotency(read["conversation_root"],
                "canvas-composer:%s:started" % hashlib.sha256(
                    body["request_id"].encode("utf-8")).hexdigest(),
                principal=browser.subject_root)
        assert started["content"] == (
            "The agent request started. An unrecorded outcome is unknown and is not retried automatically.")
    finally:
        server.close()


def test_node_conversation_create_then_bind_crash_repairs_without_second_conversation(tmp_path, monkeypatch):
    from nodelang import (
        agent_composer, application_server, commit_intent, pipeline_engines,
        universal_application,
    )
    from nodelang.cell_secret_keys import MemorySigningKeyProvider
    from nodelang.universal_pipeline import create_engine_node

    monkeypatch.setenv("ARCHHUB_GRAND_MAP_PATH",
        str(Path(universal_application.__file__).parent / "data" / "public_runtime_map.json"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
    monkeypatch.setattr(pipeline_engines, "brain_recall", lambda params, feeds: ({"out": ""}, ""))
    monkeypatch.setattr(agent_composer, "_chat",
        lambda prompt, context_block, model, **kwargs: json.dumps({"actions": [], "answer": "repaired"}))

    keys = MemorySigningKeyProvider("archhub.local.relationship-authority", secrets.token_bytes(32))
    keys.add_key("archhub.local.court-attestation", secrets.token_bytes(32))
    (tmp_path / "workspace").mkdir()
    server = application_server.ApplicationServer(universal_state_path=tmp_path / "app.sqlite3",
        universal_key_provider=keys, universal_workspace_root=tmp_path / "workspace",
        enable_machine_transport=False, enable_universal_cloud_gateway=False,
        enable_machine_projection_prewarm=False, live_watch=False).start()

    def request(path, body=None, expected=200):
        call = Request(server.url + path, headers={"Content-Type": "application/json",
            "Origin": server.url, "Cookie": "ArchHub-Session=" + server.browser_session_token,
            "X-ArchHub-Session": server.browser_session_token,
            "X-ArchHub-CSRF": server.browser_csrf_token},
            data=None if body is None else json.dumps(body).encode())
        try:
            with urlopen(call, timeout=120) as response:
                status, result = response.status, json.loads(response.read())
        except HTTPError as exc:
            status, result = exc.code, json.loads(exc.read())
        assert status == expected, result
        return result

    original_create_property = universal_application.create_universal_property
    crashed = {"done": False}

    def crash_once(*args, **kwargs):
        if not crashed["done"] and args[3] == "conversation":
            crashed["done"] = True
            raise RuntimeError("fixture crash between conversation create and node bind")
        return original_create_property(*args, **kwargs)

    try:
        browser = server._resolve_browser_session(server.browser_session_token)
        with server.mutation_lock:
            with commit_intent.declare(commit_intent.USER_ACTION, actor="court",
                                       reason="the user places a node-chat fixture"):
                node = create_engine_node(server.universal_store, server.universal_registry,
                    title="Repair node", engine="library.think", properties={"model": "court/free"},
                    authentication_context=browser.context)["root"]
        monkeypatch.setattr(universal_application, "create_universal_property", crash_once)
        body = {"prompt": "bind this once", "model": "court/free",
            "node": node, "request_id": "n-bind-1"}
        request("/api/universal/agent", body, expected=400)
        deterministic = application_server._agent_node_conversation_root(server.universal_registry, node)
        monkeypatch.setattr(universal_application, "create_universal_property", original_create_property)
        repaired = request("/api/universal/agent", body)
        assert repaired["answer"] == "repaired"
        scope = request("/api/universal/canvas")["scope"]["current"]
        read = request("/api/universal/workshop-transcript?" + urlencode(
            {"node": node, "scope": scope}))
        assert read["conversation_root"] == deterministic
        assert len({read["conversation_root"]}) == 1
    finally:
        server.close()


def test_two_concurrent_node_sends_create_one_conversation(tmp_path, monkeypatch):
    from nodelang import (
        agent_composer, application_server, commit_intent, pipeline_engines,
        universal_application,
    )
    from nodelang.cell_secret_keys import MemorySigningKeyProvider
    from nodelang.universal_pipeline import create_engine_node

    monkeypatch.setenv("ARCHHUB_GRAND_MAP_PATH",
        str(Path(universal_application.__file__).parent / "data" / "public_runtime_map.json"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
    monkeypatch.setattr(pipeline_engines, "brain_recall", lambda params, feeds: ({"out": ""}, ""))

    def fake_chat(prompt, context_block, model, **kwargs):
        time.sleep(0.15)
        return json.dumps({"actions": [], "answer": prompt.rsplit("Founder says: ", 1)[-1]})

    monkeypatch.setattr(agent_composer, "_chat", fake_chat)
    keys = MemorySigningKeyProvider("archhub.local.relationship-authority", secrets.token_bytes(32))
    keys.add_key("archhub.local.court-attestation", secrets.token_bytes(32))
    (tmp_path / "workspace").mkdir()
    server = application_server.ApplicationServer(universal_state_path=tmp_path / "app.sqlite3",
        universal_key_provider=keys, universal_workspace_root=tmp_path / "workspace",
        enable_machine_transport=False, enable_universal_cloud_gateway=False,
        enable_machine_projection_prewarm=False, live_watch=False).start()

    def request(path, body=None):
        call = Request(server.url + path, headers={"Content-Type": "application/json",
            "Origin": server.url, "Cookie": "ArchHub-Session=" + server.browser_session_token,
            "X-ArchHub-Session": server.browser_session_token,
            "X-ArchHub-CSRF": server.browser_csrf_token},
            data=None if body is None else json.dumps(body).encode())
        try:
            with urlopen(call, timeout=120) as response:
                return response.status, json.loads(response.read())
        except HTTPError as exc:
            return exc.code, json.loads(exc.read())

    try:
        browser = server._resolve_browser_session(server.browser_session_token)
        with server.mutation_lock:
            with commit_intent.declare(commit_intent.USER_ACTION, actor="court",
                                       reason="the user places a node-chat fixture"):
                node = create_engine_node(server.universal_store, server.universal_registry,
                    title="Concurrent node", engine="library.think", properties={"model": "court/free"},
                    authentication_context=browser.context)["root"]
        results = []
        threads = [threading.Thread(target=lambda i=i: results.append(request("/api/universal/agent", {
            "prompt": "concurrent %d" % i, "model": "court/free", "node": node,
            "request_id": "n-conc-%d" % i}))) for i in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        scope = request("/api/universal/canvas")[1]["scope"]["current"]
        read = request("/api/universal/workshop-transcript?" + urlencode({"node": node, "scope": scope}))[1]
        assert read["conversation_root"] == application_server._agent_node_conversation_root(
            server.universal_registry, node)
        assert sum(1 for status, _body in results if status == 200) == 1
        assert len({read["conversation_root"]}) == 1
    finally:
        server.close()
def test_universal_agent_free_route_uses_running_lmstudio_after_openrouter_refusal(monkeypatch, tmp_path):
    from nodelang import agent_composer, application_server, model_router, universal_application

    class Store:
        revision = 7

    sent = []
    timeouts = []

    def fake_urlopen(request, timeout=None):
        sent.append(request)
        timeouts.append(timeout)
        if request.full_url == model_router.OPENROUTER_CHAT:
            raise urllib.error.HTTPError(
                model_router.OPENROUTER_CHAT,
                503,
                "Service Unavailable",
                {},
                io.BytesIO(b'{"error":{"message":"first free model is unavailable"}}'),
            )
        if request.full_url == "http://127.0.0.1:1234/api/v0/models":
            return _Answer(json.dumps({
                "data": [
                    {"id": "qwen2.5-coder-7b-instruct", "object": "model",
                     "state": "loaded", "type": "llm"},
                    {"id": "text-embedding-nomic-embed-text-v1.5", "object": "model",
                     "state": "loaded", "type": "embedding"},
                ],
                "object": "list",
            }).encode("utf-8"))
        if request.full_url == model_router.LM_STUDIO_CHAT:
            return _Answer(json.dumps({
                "model": "qwen2.5-coder-7b-instruct",
                "choices": [{"message": {"role": "assistant", "content": '{"actions":[],"answer":"LOCAL"}'}}],
            }).encode("utf-8"))
        raise AssertionError("unexpected provider call %s" % request.full_url)

    monkeypatch.setenv("OPENROUTER_API_KEY", "or-live-key")
    monkeypatch.setenv("OPENROUTER_FREE_MODELS", "x")
    monkeypatch.setenv("ARCHHUB_TEST_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(model_router.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(model_router, "probe_local_runtimes", lambda: {1234: True, 11434: False})
    monkeypatch.setattr(
        universal_application,
        "project_universal_canvas",
        lambda *args, **kwargs: {"scope": {"current": "scope-a"}, "nodes": [], "catalog": [], "properties": []},
    )
    model_router.bind_local_cli_broker(None)
    result = agent_composer.run_agent_composer(
        Store(),
        object(),
        "Reply with LOCAL.",
        model="openrouter/free",
        generation={"max_tokens": 16},
        **application_server._agent_node_request_kwargs({"prompt": "Reply with LOCAL.", "model": "openrouter/free"}),
    )

    assert result["answer"] == "LOCAL"
    assert result["via"] == {
        "family": "lmstudio",
        "model": "qwen2.5-coder-7b-instruct",
        "provider": "LM Studio",
    }
    assert [request.full_url for request in sent] == [
        model_router.OPENROUTER_CHAT,
        "http://127.0.0.1:1234/api/v0/models",
        model_router.LM_STUDIO_CHAT,
    ]
    assert timeouts[0] <= 20.0
    assert timeouts[-1] >= 29.0
    assert (tmp_path / "free-chat-trace.jsonl").is_file()
