import io
import json
import sys
import urllib.error
from pathlib import Path


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
