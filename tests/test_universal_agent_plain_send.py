import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


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
