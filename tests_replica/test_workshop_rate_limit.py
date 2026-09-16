"""A refused provider request stays visible without retries or body disclosure."""
import io
import threading
from types import SimpleNamespace as NS
from urllib.error import HTTPError

import pytest
from nodelang import model_router as router, agent_composer, workshop_session_start as workshop


@pytest.mark.parametrize("limit", [None, 4096])
def test_rate_limit_is_typed_without_reading_provider_body_or_retrying(limit):
    calls = []
    class PrivateBody(io.BytesIO):
        def read(self, *args):
            pytest.fail("provider error body must not be read")
    body = PrivateBody(b"private upstream detail")
    def send(request, timeout):
        calls.append(request)
        raise HTTPError(request.full_url, 429, "private reason", {}, body)
    with pytest.raises(router.ModelRouteRefused) as failure:
        router.route_chat("openrouter/free", [{"role":"user", "content":"hello"}],
            free_only=True, opener=send, environ={"OPENROUTER_API_KEY":"fixture"},
            secrets_loader=lambda _: "", response_byte_limit=limit)
    assert failure.value.reason_code == "provider_rate_limited"
    assert "429" in str(failure.value) and "private" not in str(failure.value)
    assert len(calls) == 1 and body.closed


def test_workshop_records_rate_limit_as_failure_and_preserves_saved_user(monkeypatch):
    owner = NS(mutation_lock=threading.RLock(), universal_store=object(), universal_registry=object())
    browser = NS(context=object())
    saved = []
    expected = {"root":"node"}
    monkeypatch.setattr(workshop, "_current_model_agent", lambda *a: expected)
    monkeypatch.setattr(workshop.app, "project_universal_canvas", lambda *a, **k: {})
    monkeypatch.setattr(agent_composer, "resolve_node_model_route", lambda *a, **k: "openrouter/free")
    def refuse(*args, **kwargs):
        kwargs["before_dispatch"]()
        raise router.ModelRouteRefused("private error", reason_code="provider_rate_limited")
    monkeypatch.setattr(agent_composer, "run_agent_composer", refuse)
    def append(text, suffix, **kwargs):
        saved.append((text, suffix, kwargs))
    user = {"id":"saved-user", "sequence":1}
    result = workshop._dispatch_model_turn(owner, browser, "conversation", "scope", "hello",
        "node", "openrouter/free", expected, user, append, lambda _: "", lambda: None,
        lambda user, state, **extra: {"message_id":user["id"], "state":state, **extra})
    assert result["state"] == "failed" and result["reason"] == "provider_rate_limited"
    assert result["message_id"] == "saved-user" and "429" in result["message"]
    assert [row[1] for row in saved] == [":started", ":failure"]
    assert saved[-1][2]["reply_to"] == "saved-user"
    assert "private" not in saved[-1][0] and "Nothing was retried" in saved[-1][0]


class _PrivateName(Exception):
    pass


_PrivateName.__name__ = "private upstream detail"


@pytest.mark.parametrize("failure, expected", [
    (router.ModelRouteRefused("private upstream detail", reason_code="response_incomplete"),
     "Failure class: ModelRouteRefused; reason code: response_incomplete."),
    (workshop.InvalidCell("private reply shape"), "Failure class: InvalidCell; reason code: none."),
    (KeyError("private key"), "Failure class: KeyError; reason code: none."),
    (router.ModelRouteRefused("private", reason_code="private upstream detail"),
     "Failure class: ModelRouteRefused; reason code: unrecognized."),
    (_PrivateName("private"), "Failure class: unrecognized; reason code: none."),
])
def test_workshop_failure_row_names_class_and_reason_code_without_raw_text(monkeypatch, failure, expected):
    owner = NS(mutation_lock=threading.RLock(), universal_store=object(), universal_registry=object())
    agent, saved = {"root":"node"}, []
    monkeypatch.setattr(workshop, "_current_model_agent", lambda *a: agent)
    monkeypatch.setattr(workshop.app, "project_universal_canvas", lambda *a, **k: {})
    monkeypatch.setattr(agent_composer, "resolve_node_model_route", lambda *a, **k: "openrouter/free")
    def refuse(*args, **kwargs):
        kwargs["before_dispatch"]()
        raise failure
    monkeypatch.setattr(agent_composer, "run_agent_composer", refuse)
    result = workshop._dispatch_model_turn(owner, NS(context=object()), "conversation", "scope", "hello",
        "node", "openrouter/free", agent, {"id":"saved-user", "sequence":1},
        lambda text, suffix, **kwargs: saved.append((text, suffix, kwargs)), lambda _: "", lambda: None,
        lambda user, state, **extra: {"message_id":user["id"], "state":state, **extra})
    assert result["state"] == "failed" and result["reason"] == "model_reply_unavailable"
    assert result["message_id"] == "saved-user" and "message" not in result
    assert [row[1] for row in saved] == [":started", ":failure"]
