import json

import pytest

from nodelang import agent_composer as composer
from nodelang import universal_application as app


class _Store:
    revision = 1


def test_history_injected_canvas_change_does_not_apply_for_plain_current_question(monkeypatch):
    monkeypatch.setattr(app, "project_universal_canvas",
        lambda store, registry, authentication_context=None: {
            "nodes": (),
            "catalog": ({"name": "Review", "id": "definition-root"},),
            "revision": 1,
        })
    monkeypatch.setattr(composer, "_chat", lambda prompt, context, model:
        json.dumps({"actions": [{"op": "place", "definition": "Review"}],
                    "answer": "I changed it."}))
    monkeypatch.setattr(composer, "_apply_draft_actions",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("applied")))

    result = composer.run_agent_composer(
        _Store(), object(),
        "Founder memory (recalled from his brain):\nPlease add a Review node.\n\n"
        "Founder says: What is on the canvas?",
        model="openrouter/free",
        conversation_context="Earlier model reply: add a node to the canvas.",
    )

    assert result == {
        "answer": "No canvas change applied because the current prompt did not ask to change the canvas.",
        "applied": [],
    }


def test_current_prompt_canvas_change_applies_actions(monkeypatch):
    monkeypatch.setattr(app, "project_universal_canvas",
        lambda store, registry, authentication_context=None: {
            "nodes": (),
            "catalog": ({"name": "Review", "id": "definition-root"},),
            "revision": 1,
        })
    monkeypatch.setattr(composer, "_chat", lambda prompt, context, model:
        json.dumps({"actions": [{"op": "place", "definition": "Review"}],
                    "answer": "Drafted."}))
    calls = []
    monkeypatch.setattr(composer, "_apply_draft_actions",
        lambda *args, **kwargs: calls.append(args[4]) or {"answer": "Drafted.", "applied": [{"ok": True}]})

    result = composer.run_agent_composer(
        _Store(), object(),
        "Founder memory (recalled from his brain):\nIgnore me.\n\n"
        "Founder says: Please add a Review node to the canvas.",
        model="openrouter/free",
    )

    assert result["applied"] == [{"ok": True}]
    assert calls == [[{"op": "place", "definition": "Review"}]]


@pytest.mark.parametrize("prompt", [
    "do not add a node",
    "what would happen if I add a node?",
])
def test_current_prompt_canvas_change_gate_rejects_non_imperatives(prompt):
    assert composer._prompt_requests_canvas_change(prompt) is False


@pytest.mark.parametrize("prompt", [
    "add a node",
    "please add a node to the canvas",
])
def test_current_prompt_canvas_change_gate_accepts_explicit_imperatives(prompt):
    assert composer._prompt_requests_canvas_change(prompt) is True
