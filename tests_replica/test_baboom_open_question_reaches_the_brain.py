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
    universal_store = object()
    universal_registry = object()
    pipeline_effect_engines = {}


def test_open_question_answers_brain_first_then_model(monkeypatch):
    seen = {}

    def fake_recall(params, feeds):
        seen["recall"] = params["prompt"]
        return ({"out": "fact one\nfact two\n"}, "2 lines")

    def fake_composer(store, registry, prompt, *, model, effect_engines, authentication_context):
        seen["prompt"] = prompt
        return {"actions": [], "answer": "We decided on the share, not Azure."}

    import nodelang.pipeline_engines as engines
    import nodelang.agent_composer as composer
    monkeypatch.setattr(engines, "brain_recall", fake_recall)
    monkeypatch.setattr(composer, "run_agent_composer", fake_composer)

    payload = {"ok": True, "command": {"intent": "open-question", "payload": "q"},
               "response": {"kind": "command-guidance", "summary": "Use a known BABOOM command"}}
    out = app_server.answer_open_question(_Owner(), "what did we decide about signing?", None, payload)

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
    source = inspect.getsource(app_server.ApplicationServer.dispatch_universal_machine_route)
    branch = source[source.index('path == "/api/universal/baboom-command-response"'):]
    branch = branch[:branch.index('path == "/api/universal/baboom-command-execute"')]
    assert "answer_open_question(" in branch, "the dispatcher must answer open questions"
    lock_at = branch.index("with self.mutation_lock:")
    answer_at = branch.index("answer_open_question(")
    assert answer_at > lock_at, "the answer is composed after the locked read"
    locked_block = branch[lock_at:answer_at]
    assert "return respond_universal_baboom_utterance" not in locked_block, (
        "the dispatcher must not return the canned response from inside the lock"
    )
