"""BABOOM free text reaches the founder's brain on the path the companion uses.

The audit found the brain-first answer existed only on the browser HTTP
handler, while the shipped companion and the cloud gateway enter through
dispatch_universal_machine_route -- which returned the catalogue's canned
menu. One helper now answers on both paths; these courts hold that.
"""
from __future__ import annotations

import inspect

import nodelang.application_server as app_server


class _Owner:
    """The owner surface answer_open_question uses: one planning slot, the
    authority it rechecks after the unlocked model wait, and the picked model."""

    def __init__(self):
        import threading

        self.universal_store = object()
        self.universal_registry = object()
        self.pipeline_effect_engines = {}
        self.mutation_lock = threading.Lock()
        self._composer_planning_slot = threading.BoundedSemaphore(1)
        self._runtime_handoff_exit = threading.Event()
        self.universal_checkpoint_guard = None
        self.rechecked = []

    def require_universal_http_route(self, method, path, **kwargs):
        self.rechecked.append(path)

    def _read_agent_model(self):
        return "picked-model"


def test_open_question_answers_brain_first_then_model(monkeypatch):
    seen = {}

    def fake_recall(params, feeds):
        seen["recall"] = params["prompt"]
        return ({"out": "fact one\nfact two\n"}, "2 lines")

    def fake_composer(store, registry, prompt, *, model, effect_engines, authentication_context,
                      mutation_lock, revalidate):
        seen["prompt"], seen["model"] = prompt, model
        revalidate()
        return {"actions": [], "answer": "We decided on the share, not Azure."}

    import nodelang.pipeline_engines as engines
    import nodelang.agent_composer as composer
    monkeypatch.setattr(engines, "brain_recall", fake_recall)
    monkeypatch.setattr(composer, "run_agent_composer", fake_composer)

    payload = {"ok": True, "command": {"intent": "open-question", "payload": "q"},
               "response": {"kind": "command-guidance", "summary": "Use a known BABOOM command"}}
    owner = _Owner()
    out = app_server.answer_open_question(owner, "what did we decide about signing?", None, payload)
    assert seen["model"] == "picked-model"
    assert owner.rechecked == ["/api/universal/baboom-command-response"], (
        "authority is rechecked after the unlocked model wait")

    assert seen["recall"] == "what did we decide about signing?", "the brain is asked first"
    assert "fact one" in seen["prompt"] and "Founder says:" in seen["prompt"], "recall is in the model prompt"
    assert out["command"]["intent"] == "ask"
    assert out["response"]["kind"] == "answer"
    assert out["response"]["summary"] == "We decided on the share, not Azure."
    assert out["response"]["data"]["brain_context_lines"] == 2


def test_a_dead_brain_costs_the_recall_never_the_answer(monkeypatch):
    import nodelang.pipeline_engines as engines
    import nodelang.agent_composer as composer
    monkeypatch.setattr(engines, "brain_recall", lambda p, f: (_ for _ in ()).throw(RuntimeError("daemon down")))
    monkeypatch.setattr(composer, "run_agent_composer",
                        lambda *a, **k: {"actions": [], "answer": "still answered"})
    out = app_server.answer_open_question(_Owner(), "hello", None,
                                          {"command": {"intent": "open-question"}, "response": {}})
    assert out["response"]["summary"] == "still answered"
    assert out["response"]["data"]["brain_context_lines"] == 0


def test_the_machine_dispatcher_answers_open_questions_too():
    """The path the shipped companion actually uses must call the same helper,
    and must do so outside the mutation lock."""
    # dispatch_universal_machine_route delegates to the method that holds the routes.
    source = inspect.getsource(app_server.ApplicationServer._dispatch_universal_machine_route)
    branch = source[source.index('path == "/api/universal/baboom-command-response"'):]
    branch = branch[:branch.index('path == "/api/universal/baboom-command-execute"')]
    assert "_require_founder_machine_session(request, direct, path)" in branch
    assert "answer_open_question(" in branch, "the dispatcher must answer open questions"
    lock_at = branch.index("with self.mutation_lock:")
    answer_at = branch.index("answer_open_question(")
    assert answer_at > lock_at, "the answer is composed after the locked read"
    locked_block = branch[lock_at:answer_at]
    assert "return respond_universal_baboom_utterance" not in locked_block, (
        "the dispatcher must not return the canned response from inside the lock"
    )


def test_the_studio_composer_is_brain_first_too(monkeypatch):
    import nodelang.pipeline_engines as engines
    monkeypatch.setattr(engines, "brain_recall", lambda p, f: ({"out": "he prefers millimetres"}, "1"))
    prompt = app_server.brain_first_prompt("draw the wall")
    assert "he prefers millimetres" in prompt and prompt.endswith("Founder says: draw the wall")
    source = inspect.getsource(app_server.ApplicationServer)
    agent_branch = source[source.index("self.path == '/api/universal/agent'"):][:3000]
    assert "brain_first_prompt(" in agent_branch, "the studio composer must recall before it asks the model"
