"""The model picked is the model asked, at its own address.

The picker offered the founder's cloud, OpenRouter, LM Studio and Ollama.
Every one of them posted to one hardcoded OpenRouter URL, so a local model
answered as gpt-4o and no cloud request was ever made. The canvas composer
ignored the picker entirely and dropped the reply on the floor, and on a
colleague's fresh install no key was found and nothing said so.

These courts hold the route to its own host, payload and key, hold an unknown
route to a refusal instead of a default, and hold the composer to sending the
selected model and showing the answer where it was typed.
"""
from __future__ import annotations

import io
import urllib.error
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from nodelang import model_catalogue, model_router
from nodelang.model_router import (
    LM_STUDIO_CHAT,
    ModelRouteRefused,
    OLLAMA_CHAT,
    OPENROUTER_CHAT,
    discover_key,
    resolve_model_route,
    route_chat,
)

ROOT = Path(__file__).resolve().parents[1]
NO_SECRETS = lambda name: ""


class _Answer(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *unused):
        return False


class _Wire:
    """The HTTP layer, faked: what was sent, and what comes back."""

    def __init__(self, payload=None, raises=None):
        self.payload = payload
        self.raises = raises
        self.sent = []

    def __call__(self, request, timeout=None):
        self.sent.append(request)
        if self.raises is not None:
            raise self.raises
        return _Answer(json.dumps(self.payload).encode("utf-8"))

    @property
    def body(self):
        return json.loads(self.sent[-1].data.decode("utf-8"))

    @property
    def url(self):
        return self.sent[-1].full_url

    def header(self, name):
        return self.sent[-1].headers.get(name)


def _openai_answer(text):
    return {"choices": [{"message": {"role": "assistant", "content": text}}]}


ASK = [{"role": "user", "content": "how many walls"}]


class _SequenceWire:
    """HTTP fake that returns one payload per call."""

    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.sent = []

    def __call__(self, request, timeout=None):
        self.sent.append(request)
        if not self.payloads:
            raise AssertionError("unexpected extra provider call")
        payload = self.payloads.pop(0)
        if isinstance(payload, BaseException):
            raise payload
        return _Answer(json.dumps(payload).encode("utf-8"))

    @property
    def bodies(self):
        return [json.loads(request.data.decode("utf-8")) for request in self.sent]


def test_a_local_lm_studio_model_reaches_lm_studio_and_nothing_else():
    wire = _Wire(_openai_answer("47 walls"))
    out = route_chat("lmstudio/qwen2.5-coder-7b", ASK, opener=wire,
                     environ={}, secrets_loader=NO_SECRETS, cloud_session=None)
    assert wire.url == LM_STUDIO_CHAT
    assert wire.url.startswith("http://127.0.0.1:1234/")
    assert wire.body["model"] == "qwen2.5-coder-7b"
    assert wire.body["messages"] == ASK
    # a machine on the desk needs no key, and must not be handed one
    assert wire.header("Authorization") is None
    assert out["text"] == "47 walls"
    assert out["family"] == "lmstudio" and out["key_source"] == "not required"


def test_an_ollama_model_reaches_ollamas_own_endpoint_and_body_shape():
    wire = _Wire({"message": {"role": "assistant", "content": "done"}})
    out = route_chat("ollama/llama3.3:70b", ASK, opener=wire,
                     environ={}, secrets_loader=NO_SECRETS, cloud_session=None)
    assert wire.url == OLLAMA_CHAT
    assert wire.url.startswith("http://127.0.0.1:11434/api/chat")
    assert wire.body["model"] == "llama3.3:70b"
    assert wire.body["stream"] is False, "one answer, not a stream"
    assert wire.body["messages"] == ASK
    assert wire.header("Authorization") is None
    assert out["text"] == "done", "ollama answers in message.content"


def test_a_byo_model_reaches_openrouter_with_the_key_from_the_environment():
    wire = _Wire(_openai_answer("ok"))
    out = route_chat("deepseek/deepseek-r1", ASK, opener=wire,
                     environ={"OPENROUTER_API_KEY": "or-live-key"},
                     secrets_loader=NO_SECRETS, cloud_session=None)
    assert wire.url == OPENROUTER_CHAT
    assert wire.body["model"] == "deepseek/deepseek-r1"
    assert wire.header("Authorization") == "Bearer or-live-key"
    assert out["family"] == "openrouter" and out["key_source"] == "environment"


def test_generation_defaults_are_carried_to_the_openrouter_request_body():
    wire = _Wire(_openai_answer("ok"))
    route_chat("deepseek/deepseek-r1", ASK, opener=wire,
               environ={"OPENROUTER_API_KEY": "or-live-key"},
               secrets_loader=NO_SECRETS, cloud_session=None,
               temperature=0.35, top_p=0.81, max_tokens=2048)
    assert wire.body["temperature"] == 0.35
    assert wire.body["top_p"] == 0.81
    assert wire.body["max_tokens"] == 2048


def test_an_explicit_openrouter_free_model_keeps_its_vendor_id_and_zero_price_guard():
    wire = _Wire({**_openai_answer("ok"), "model": "nvidia/nemotron-3-ultra-550b-a55b:free",
                  "usage": {"cost": 0}})
    out = route_chat("nvidia/nemotron-3-ultra-550b-a55b:free", ASK,
                     opener=wire, environ={"OPENROUTER_API_KEY": "or-live-key"},
                     secrets_loader=NO_SECRETS, cloud_session=None, free_only=True)
    assert wire.url == OPENROUTER_CHAT
    assert wire.header("Authorization") == "Bearer or-live-key"
    assert wire.body["model"] == "nvidia/nemotron-3-ultra-550b-a55b:free"
    assert wire.body["provider"]["allow_fallbacks"] is False
    assert wire.body["provider"]["max_price"]["request"] == 0
    assert out["family"] == "openrouter"


def test_openrouter_error_object_surfaces_message_without_shape_refusal():
    wire = _Wire({"error": {"message": "rate limited, try again in 20 s"}})
    with pytest.raises(ModelRouteRefused, match="OpenRouter: rate limited, try again in 20 s") as failure:
        route_chat("deepseek/deepseek-r1", ASK, opener=wire,
                   environ={"OPENROUTER_API_KEY": "or-live-key"},
                   secrets_loader=NO_SECRETS, cloud_session=None)
    assert len(wire.sent) == 1
    assert "shape this app does not read" not in str(failure.value)


def test_openrouter_free_http_errors_rotate_until_neutral_exhaustion():
    wire = _SequenceWire([
        urllib.error.HTTPError(
            OPENROUTER_CHAT, 429, "Too Many Requests", {},
            io.BytesIO(b'{"error":{"message":"first free model is rate limited"}}'),
        ),
        urllib.error.HTTPError(
            OPENROUTER_CHAT, 503, "Service Unavailable", {},
            io.BytesIO(b'{"error":{"message":"second free model is unavailable"}}'),
        ),
        urllib.error.HTTPError(
            OPENROUTER_CHAT, 503, "Service Unavailable", {},
            io.BytesIO(b'{"error":{"message":"third free model is unavailable"}}'),
        ),
    ])
    with pytest.raises(ModelRouteRefused) as failure:
        route_chat("openrouter/free", ASK, opener=wire,
                   environ={"OPENROUTER_API_KEY": "or-live-key",
                            "OPENROUTER_FREE_MODELS": "one/free:free,two/free:free"},
                   secrets_loader=NO_SECRETS, cloud_session=None, free_only=True)
    assert str(failure.value) == "No free model answered right now. Try again shortly."
    assert [body["model"] for body in wire.bodies] == ["openrouter/free", "one/free:free", "two/free:free"]
    assert "first free model" not in str(failure.value)


def test_openrouter_free_first_attempt_body_matches_the_head_router_contract():
    wire = _SequenceWire([{**_openai_answer("router answered"), "model": "some/free:free"}])
    out = route_chat("openrouter/free", ASK, opener=wire,
                     environ={"OPENROUTER_API_KEY": "or-live-key",
                              "OPENROUTER_FREE_MODELS": "one/free:free,two/free:free"},
                     secrets_loader=NO_SECRETS, cloud_session=None, free_only=True)
    assert out["text"] == "router answered"
    assert len(wire.sent) == 1
    assert wire.bodies[0] == {
        "model": "openrouter/free",
        "messages": ASK,
        "max_tokens": 900,
        "temperature": 0.0,
        "provider": {
            "max_price": {"prompt": 0, "completion": 0, "request": 0, "image": 0},
            "allow_fallbacks": False,
        },
    }


def test_openrouter_free_404_unavailable_for_free_rotates_to_next_free_model():
    wire = _SequenceWire([
        urllib.error.HTTPError(
            OPENROUTER_CHAT, 404, "Not Found", {},
            io.BytesIO(b'{"error":{"message":"This model is unavailable for free."}}'),
        ),
        {**_openai_answer("fallback free"), "model": "one/free:free"},
    ])
    out = route_chat("openrouter/free", ASK, opener=wire,
                     environ={"OPENROUTER_API_KEY": "or-live-key",
                              "OPENROUTER_FREE_MODELS": "one/free:free,two/free:free"},
                     secrets_loader=NO_SECRETS, cloud_session=None, free_only=True)
    assert out["text"] == "fallback free"
    assert [body["model"] for body in wire.bodies] == ["openrouter/free", "one/free:free"]


def test_openrouter_free_never_relays_paid_slug_advice():
    paid_slug = "mistralai/mistral-small-3.2-24b-instruct"
    wire = _SequenceWire([
        urllib.error.HTTPError(
            OPENROUTER_CHAT, 404, "Not Found", {},
            io.BytesIO(json.dumps({"error": {"message": (
                "OpenRouter: This model is unavailable for free. The paid version "
                "is available now - use this slug instead: %s" % paid_slug)}}).encode("utf-8")),
        ),
        urllib.error.HTTPError(
            OPENROUTER_CHAT, 404, "Not Found", {},
            io.BytesIO(json.dumps({"error": {"message": (
                "No endpoints found for %s; paid version only." % paid_slug)}}).encode("utf-8")),
        ),
    ])
    with pytest.raises(ModelRouteRefused) as failure:
        route_chat("openrouter/free", ASK, opener=wire,
                   environ={"OPENROUTER_API_KEY": "or-live-key",
                            "OPENROUTER_FREE_MODELS": "one/free:free"},
                   secrets_loader=NO_SECRETS, cloud_session=None, free_only=True)
    said = str(failure.value)
    assert said == "No free model answered right now. Try again shortly."
    assert "paid version" not in said.casefold()
    assert "use this slug" not in said.casefold()
    assert paid_slug not in said


def test_openrouter_free_exhaustion_gives_neutral_message():
    wire = _SequenceWire([
        urllib.error.HTTPError(
            OPENROUTER_CHAT, 400, "Bad Request", {},
            io.BytesIO(b'{"error":{"message":"not free; no endpoints found"}}'),
        ),
        urllib.error.HTTPError(
            OPENROUTER_CHAT, 404, "Not Found", {},
            io.BytesIO(b'{"error":{"message":"model unavailable for free"}}'),
        ),
    ])
    with pytest.raises(ModelRouteRefused) as failure:
        route_chat("openrouter/free", ASK, opener=wire,
                   environ={"OPENROUTER_API_KEY": "or-live-key",
                            "OPENROUTER_FREE_MODELS": "one/free:free"},
                   secrets_loader=NO_SECRETS, cloud_session=None, free_only=True)
    assert str(failure.value) == "No free model answered right now. Try again shortly."


def test_opencode_free_post_dispatch_failure_does_not_replay_to_openrouter(monkeypatch):
    class Broker:
        def __init__(self):
            self.calls = []

        def local_cli_executable(self, assistant):
            return "C:/tools/opencode.exe" if assistant == "opencode" else None

        def chat(self, assistant, model, messages, *, timeout_seconds):
            self.calls.append((assistant, model, messages, timeout_seconds))
            return {"ok": False, "error_code": "invalid_model_output"}

    broker = Broker()
    wire = _SequenceWire([{**_openai_answer("fallback free"), "model": "one/free:free"}])
    guard_calls = []
    monkeypatch.setattr(model_router, "installed_cli_version",
                        lambda executable, **_k: model_router._CLI_VERIFIED_VERSIONS["opencode"])
    model_router.bind_local_cli_broker(broker)
    try:
        with pytest.raises(ModelRouteRefused, match="OpenCode .* did not answer"):
            route_chat("local-cli/opencode", ASK, opener=wire,
                       environ={"OPENROUTER_API_KEY": "or-live-key",
                                "OPENROUTER_FREE_MODELS": "one/free:free,two/free:free"},
                       secrets_loader=NO_SECRETS, cloud_session=None, free_only=True,
                       before_dispatch=lambda: guard_calls.append("once"))
    finally:
        model_router.bind_local_cli_broker(None)
    assert len(broker.calls) == 1
    assert len(wire.sent) == 0
    assert guard_calls == ["once"]


def test_opencode_free_pre_dispatch_failure_falls_through_once_to_openrouter(monkeypatch):
    class Broker:
        def __init__(self):
            self.calls = []

        def local_cli_executable(self, assistant):
            return None

        def chat(self, assistant, model, messages, *, timeout_seconds):
            self.calls.append((assistant, model, messages, timeout_seconds))
            raise AssertionError("pre-dispatch failure must not call the broker chat")

    broker = Broker()
    wire = _SequenceWire([{**_openai_answer("fallback free"), "model": "one/free:free"}])
    monkeypatch.setattr(model_router, "installed_cli_version",
                        lambda executable, **_k: model_router._CLI_VERIFIED_VERSIONS["opencode"])
    model_router.bind_local_cli_broker(broker)
    try:
        out = route_chat("local-cli/opencode", ASK, opener=wire,
                         environ={"OPENROUTER_API_KEY": "or-live-key",
                                  "OPENROUTER_FREE_MODELS": "one/free:free,two/free:free"},
                         secrets_loader=NO_SECRETS, cloud_session=None, free_only=True)
    finally:
        model_router.bind_local_cli_broker(None)
    assert out["text"] == "fallback free"
    assert out["family"] == "openrouter"
    assert len(broker.calls) == 0
    assert len(wire.sent) == 1
    assert wire.bodies[0]["model"] == "openrouter/free"


def test_openrouter_free_rejects_a_paid_actual_model():
    wire = _Wire({**_openai_answer("paid answer"), "model": "openai/gpt-4o"})
    with pytest.raises(ModelRouteRefused, match="non-free actual model"):
        route_chat("openrouter/free", ASK, opener=wire,
                   environ={"OPENROUTER_API_KEY": "or-live-key",
                            "OPENROUTER_FREE_MODELS": "one/free:free"},
                   secrets_loader=NO_SECRETS, cloud_session=None, free_only=True)
    assert len(wire.sent) == 1


def test_provider_error_text_redacts_token_like_values():
    fake_key = "sk" + "-proj-" + ("A" * 26) + "0123456789"
    fake_bearer = "Bear" + "er " + ("a" * 26) + ("Z" * 26) + "0123456789"
    wire = _Wire(raises=urllib.error.HTTPError(
        OPENROUTER_CHAT, 400, "Bad Request", {},
        io.BytesIO(json.dumps({"error": {"message": "bad key=%s and %s" % (
            fake_key, fake_bearer)}}).encode("utf-8")),
    ))
    with pytest.raises(ModelRouteRefused) as failure:
        route_chat("deepseek/deepseek-r1", ASK, opener=wire,
                   environ={"OPENROUTER_API_KEY": "or-live-key"},
                   secrets_loader=NO_SECRETS, cloud_session=None)
    said = str(failure.value)
    assert fake_key not in said
    assert fake_bearer not in said
    assert "[redacted]" in said


def test_provider_error_text_keeps_long_words_while_redacting_credentials():
    long_word = "supercalifragilisticexpialidociouspseudopseudohypoparathyroidism"
    fake_key = "sk-" + ("A" * 24) + "12345678"
    wire = _Wire(raises=urllib.error.HTTPError(
        OPENROUTER_CHAT, 400, "Bad Request", {},
        io.BytesIO(json.dumps({"error": {"message": "word %s key %s" % (
            long_word, fake_key)}}).encode("utf-8")),
    ))
    with pytest.raises(ModelRouteRefused) as failure:
        route_chat("deepseek/deepseek-r1", ASK, opener=wire,
                   environ={"OPENROUTER_API_KEY": "or-live-key"},
                   secrets_loader=NO_SECRETS, cloud_session=None)
    said = str(failure.value)
    assert long_word in said
    assert fake_key not in said
    assert "[redacted]" in said


def test_openrouter_free_empty_content_falls_to_next_free_default():
    wire = _SequenceWire([
        {**_openai_answer(""), "model": "mistralai/mistral-small-3.2-24b-instruct:free"},
        {**_openai_answer("fallback ok"), "model": "deepseek/deepseek-chat-v3-0324:free"},
    ])
    started = []
    out = route_chat("openrouter/free", ASK, opener=wire,
                     environ={"OPENROUTER_API_KEY": "or-live-key"},
                     secrets_loader=NO_SECRETS, cloud_session=None, free_only=True,
                     before_dispatch=lambda: started.append("once"))
    assert [body["model"] for body in wire.bodies] == [
        "openrouter/free",
        "mistralai/mistral-small-3.2-24b-instruct:free",
    ]
    assert out["text"] == "fallback ok"
    assert out["actual_model"] == "deepseek/deepseek-chat-v3-0324:free"
    assert started == ["once"]


def test_openrouter_free_reasoning_only_falls_to_next_free_default():
    wire = _SequenceWire([
        {"choices": [{"message": {"role": "assistant", "reasoning": "hidden chain"},
                      "finish_reason": "stop"}],
         "model": "mistralai/mistral-small-3.2-24b-instruct:free"},
        {**_openai_answer("normal answer"), "model": "deepseek/deepseek-chat-v3-0324:free"},
    ])
    out = route_chat("openrouter/free", ASK, opener=wire,
                     environ={"OPENROUTER_API_KEY": "or-live-key"},
                     secrets_loader=NO_SECRETS, cloud_session=None, free_only=True)
    assert len(wire.sent) == 2
    assert out["text"] == "normal answer"


def test_openrouter_free_normal_content_does_not_fallback():
    wire = _SequenceWire([
        {**_openai_answer("normal answer"), "model": "mistralai/mistral-small-3.2-24b-instruct:free"},
        {**_openai_answer("must not be asked"), "model": "deepseek/deepseek-chat-v3-0324:free"},
    ])
    out = route_chat("openrouter/free", ASK, opener=wire,
                     environ={"OPENROUTER_API_KEY": "or-live-key"},
                     secrets_loader=NO_SECRETS, cloud_session=None, free_only=True)
    assert len(wire.sent) == 1
    assert wire.bodies[0]["model"] == "openrouter/free"
    assert out["text"] == "normal answer"


def test_a_cloud_model_reaches_the_founders_cloud_with_his_session():
    wire = _Wire(_openai_answer("from the cloud"))
    out = route_chat("cloud/anthropic/claude-sonnet-5", ASK, opener=wire,
                     environ={}, secrets_loader=NO_SECRETS,
                     cloud_session={"token": "sess-9", "base_url": "https://api.archhub.io"})
    assert wire.url == "https://api.archhub.io/v1/chat/completions"
    assert "openrouter" not in wire.url
    assert wire.body["model"] == "anthropic/claude-sonnet-5", "the cloud id, without the prefix"
    assert wire.header("Authorization") == "Bearer sess-9"
    assert out["family"] == "cloud" and out["key_source"] == "cloud session"


@pytest.mark.parametrize("route", ["", "   ", "gpt-4o", "banana/model/extra", "lmstudio/", "ollama/  "])
def test_a_route_with_no_provider_is_refused_never_quietly_defaulted(route):
    wire = _Wire(_openai_answer("should never be asked"))
    with pytest.raises(ModelRouteRefused) as refusal:
        route_chat(route, ASK, opener=wire, environ={"OPENROUTER_API_KEY": "k"},
                   secrets_loader=NO_SECRETS, cloud_session=None)
    assert wire.sent == [], "a route nobody can read must send nothing"
    assert len(str(refusal.value)) < 200, "short enough to show a person"


def test_the_four_families_resolve_to_four_different_hosts():
    picked = [
        resolve_model_route("lmstudio/qwen"),
        resolve_model_route("ollama/llama3"),
        resolve_model_route("openrouter/anthropic/claude-sonnet-4.5"),
        resolve_model_route("cloud/gpt-4o", cloud_base_url="https://api.archhub.io"),
    ]
    assert [one.family for one in picked] == ["lmstudio", "ollama", "openrouter", "cloud"]
    assert len({one.url for one in picked}) == 4
    assert [one.needs_key for one in picked] == [False, False, True, True]
    assert picked[2].model == "anthropic/claude-sonnet-4.5", "the prefix is not part of the id"


def test_a_provider_that_is_not_running_says_so_and_names_where_it_looked():
    import urllib.error

    wire = _Wire(raises=urllib.error.URLError("connection refused"))
    with pytest.raises(ModelRouteRefused) as refusal:
        route_chat("lmstudio/qwen", ASK, opener=wire, environ={},
                   secrets_loader=NO_SECRETS, cloud_session=None)
    said = str(refusal.value)
    assert "LM Studio" in said and "127.0.0.1:1234" in said
    assert len(said) < 120 and said.count(chr(10)) == 0, "one short line, not a paragraph"


def test_a_refused_request_is_never_answered_by_another_model():
    import urllib.error

    wire = _Wire(raises=urllib.error.HTTPError(OPENROUTER_CHAT, 401, "no", {}, None))
    with pytest.raises(ModelRouteRefused) as refusal:
        route_chat("deepseek/deepseek-r1", ASK, opener=wire,
                   environ={"OPENROUTER_API_KEY": "stale"},
                   secrets_loader=NO_SECRETS, cloud_session=None)
    assert "OpenRouter" in str(refusal.value) and "401" in str(refusal.value)
    assert len(wire.sent) == 1, "one attempt, no substitute model behind it"


def test_a_fresh_install_with_no_key_is_told_exactly_what_to_set():
    """A colleague installed it, typed, and got nothing back at all."""
    wire = _Wire(_openai_answer("never"))
    with pytest.raises(ModelRouteRefused) as refusal:
        route_chat("deepseek/deepseek-r1", ASK, opener=wire, environ={},
                   secrets_loader=NO_SECRETS, cloud_session=None)
    said = str(refusal.value)
    assert "OPENROUTER_API_KEY" in said, "name the variable, not 'no key'"
    assert "secrets store" in said
    assert wire.sent == [], "no keyless request is worth making"
    assert len(said) < 200 and said.endswith(".")


def test_a_cloud_model_with_no_session_names_signing_in():
    wire = _Wire(_openai_answer("never"))
    with pytest.raises(ModelRouteRefused) as refusal:
        route_chat("cloud/gpt-4o", ASK, opener=wire, environ={},
                   secrets_loader=NO_SECRETS, cloud_session=None)
    said = str(refusal.value)
    assert "sign in" in said and "ARCHHUB_CLOUD_TOKEN" in said
    assert wire.sent == []


def test_keys_are_looked_for_in_one_written_order():
    """Environment, then the founder's secrets store, then the cloud session."""
    assert discover_key("openrouter", environ={"OPENROUTER_API_KEY": "from-env"},
                        secrets_loader=lambda name: "from-store") == ("from-env", "environment")
    assert discover_key("openrouter", environ={},
                        secrets_loader=lambda name: "from-store") == ("from-store", "secrets store")
    assert discover_key("cloud", environ={}, secrets_loader=NO_SECRETS,
                        cloud_session={"token": "from-session"}) == ("from-session", "cloud session")
    # a local runtime is asked for no key at all
    assert discover_key("lmstudio", environ={}, secrets_loader=NO_SECRETS)[1] == "not required"


def test_the_secrets_store_is_asked_by_name_never_guessed():
    asked = []
    discover_key("openrouter", environ={}, secrets_loader=lambda name: asked.append(name) or "k")
    assert asked == ["openrouter"]


def test_the_composer_asks_the_chosen_route_and_holds_no_openrouter_url():
    import nodelang.agent_composer as composer

    seen = {}

    def fake_route_chat(route, messages, **kwargs):
        seen["route"] = route
        seen["roles"] = [m["role"] for m in messages]
        return {"text": '{"actions":[],"answer":"fine"}'}

    composer.route_chat = fake_route_chat
    try:
        assert composer._chat("q", "CANVAS", "lmstudio/qwen") == '{"actions":[],"answer":"fine"}'
    finally:
        from nodelang.model_router import route_chat as real

        composer.route_chat = real
    assert seen["route"] == "lmstudio/qwen"
    assert seen["roles"] == ["system", "user"]
    source = (ROOT / "nodelang" / "agent_composer.py").read_text(encoding="utf-8")
    assert "openrouter.ai" not in source, "the one hardcoded URL is gone"
    assert "_FALLBACK_MODEL" not in source, "a refused model is never swapped for gpt-4o"


def test_a_picked_cloud_row_is_told_apart_from_an_openrouter_row():
    """Both ids read "anthropic/x"; only the row knows which one it is."""
    cloud = {"route": "anthropic/claude-sonnet-5", "tag": "CLOUD"}
    byo = {"route": "anthropic/claude-sonnet-4.5", "tag": "BYO"}
    local = {"route": "lmstudio/qwen2.5-coder-7b", "tag": "LOCAL"}
    assert model_catalogue.routable_route(cloud) == "cloud/anthropic/claude-sonnet-5"
    assert model_catalogue.routable_route(byo) == "anthropic/claude-sonnet-4.5"
    assert model_catalogue.routable_route(local) == "lmstudio/qwen2.5-coder-7b"
    assert resolve_model_route(model_catalogue.routable_route(cloud),
                               cloud_base_url="https://api.archhub.io").family == "cloud"
    assert resolve_model_route(model_catalogue.routable_route(byo)).family == "openrouter"


def test_every_row_the_picker_receives_carries_its_routable_string():
    decorated = model_catalogue.groups_with_routes({
        "ok": True, "count": 2,
        "groups": [
            {"name": "CLOUD · subscription", "items": [{"route": "gpt-4o", "tag": "CLOUD"}]},
            {"name": "LOCAL · this machine", "items": [{"route": "ollama/llama3", "tag": "LOCAL"}]},
        ],
    })
    rows = [item for group in decorated["groups"] for item in group["items"]]
    assert [row["routed"] for row in rows] == ["cloud/gpt-4o", "ollama/llama3"]
    assert rows[0]["route"] == "gpt-4o", "the id the source published is untouched"
    assert decorated["count"] == 2 and decorated["ok"] is True


def test_the_server_hands_the_picker_routes_and_the_refusal_as_words():
    server = (ROOT / "nodelang" / "application_server.py").read_text(encoding="utf-8")
    assert "groups_with_routes(live_model_groups(session))" in server
    branch = server[server.index("'/api/universal/agent'"):]
    branch = branch[:branch.index("'/api/universal/run-graph'")]
    assert "ModelRouteRefused" in branch, "the router's refusal is caught here"
    assert "'answer': str(refused)" in branch, "and comes back as the answer to show"


def _jsx():
    return (ROOT / "nodelang" / "studio" / "studio-lm.jsx").read_text(encoding="utf-8")


def _block(source, opening, closing):
    start = source.index(opening)
    return source[start:source.index(closing, start)]


def test_the_canvas_composer_asks_the_model_that_is_selected():
    jsx = _jsx()
    composer = _block(jsx, "const FloatingComposer = ", "// ─── mini-map")
    assert "FloatingComposer = ({ setLibraryOpen, model })" in composer
    assert "model={model}" in composer, "the picked model reaches the ask"
    canvas = _block(jsx, "const NodeCanvas = ", "// Top-left hint strip")
    assert "addNodeFromLibrary, model }" in canvas, "the canvas carries it down"
    assert "<FloatingComposer setLibraryOpen={setLibraryOpen} model={model}/>" in canvas
    assert "<NodeCanvas" in jsx and "addNodeFromLibrary={addNodeFromLibrary} model={model}/>" in jsx
    ask = _block(jsx, "const InlineAsk = ", "const NodeBody = ")
    # Two of the three ask boxes are rendered without a model prop, so the
    # component falls back to the picker's published choice rather than to a
    # server default: the founder picked a local model and a cloud one
    # answered. Either way the string sent is the routable one.
    assert "window.ARCHHUB_AGENT(said, modelRoute(picked))" in ask
    assert "window.ARCHHUB_PICKED_MODEL" in ask
    assert "<ModelInWindow model={model}/>" in jsx, "the choice is published once"
    assert "model?.route" not in jsx, "the routable string, not the raw id"


def test_the_answer_is_rendered_where_the_person_typed():
    jsx = _jsx()
    composer = _block(jsx, "const FloatingComposer = ", "// ─── mini-map")
    assert "const [answer, setAnswer] = React.useState('')" in composer
    assert "onAnswer={setAnswer}" in composer, "the ask reports back into the box"
    assert "{answer && (" in composer, "and the box draws it"
    assert "whiteSpace:'pre-wrap'" in composer, "a whole answer, not a 60 character stub"
    ask = _block(jsx, "const InlineAsk = ", "const NodeBody = ")
    assert "report(answer)" in ask and "report('refused: '" in ask


def test_the_chat_rail_and_the_composer_use_the_same_route_string():
    jsx = _jsx()
    assert "const modelRoute = (m) => String((m && (m.routed || m.route)) || '');" in jsx
    routed = jsx.count("modelRoute(model)") + jsx.count("modelRoute(picked)")
    assert routed >= 3, "chat rail, composer, and every inline ask: %d" % routed
    picker = _block(jsx, "const ModelPicker = ", "// ──────────────────────── DOCS")
    assert picker.count("routed:'cloud/") == 3, "every offline CLOUD row routes to the cloud"


def test_the_studio_source_still_compiles():
    """A composer that does not parse shows nothing at all, silently."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not on this machine")
    script = (
        "const fs=require('fs'),vm=require('vm');"
        "const s={navigator:{userAgent:'node'},console};"
        "s.window=s;s.self=s;s.global=s;vm.createContext(s);"
        "vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),s,{filename:'babel.js'});"
        "const out=s.Babel.transform(fs.readFileSync(process.argv[2],'utf8'),{presets:['react']});"
        "process.stdout.write(String(out.code.length));"
    )
    done = subprocess.run(
        [node, "-e", script,
         str(ROOT / "nodelang" / "studio" / "vendor" / "babel.js"),
         str(ROOT / "nodelang" / "studio" / "studio-lm.jsx")],
        capture_output=True, text=True, timeout=180,
    )
    assert done.returncode == 0, done.stderr[-600:]
    assert int(done.stdout) > 100_000


def test_there_is_no_hidden_default_model():
    """A model nobody chose answered for months: the composer fell back to a
    route hidden in the source, on OpenRouter, for money. A default is DECLARED
    or it does not exist; without one and without a pick, the composer says
    what to pick instead of guessing."""
    import inspect

    from nodelang import agent_composer as ac

    src = inspect.getsource(ac)
    assert 'os.environ.get("ARCHHUB_AGENT_MODEL", "")' in src
    assert 'os.environ.get(' + chr(10) + '    "ARCHHUB_AGENT_MODEL", "anthropic/claude-sonnet-4.5"' not in src, (
        "the old hidden route must not survive as a fallback")
    assert '"ARCHHUB_AGENT_MODEL", "anthropic' not in src
    assert "raise InvalidCell(NO_MODEL_CHOSEN)" in src
    assert "picker" in ac.NO_MODEL_CHOSEN and "ARCHHUB_AGENT_MODEL" in ac.NO_MODEL_CHOSEN


def test_the_studio_pick_is_remembered_for_the_companion():
    """BABOOM and the relay have no picker; they used to fall through to the
    hidden default. They ride the founder's last studio pick now."""
    from pathlib import Path

    server = (Path(__file__).resolve().parents[1] / "nodelang" / "application_server.py").read_text(encoding="utf-8")
    assert "def _remember_agent_model(self, route: str) -> str:" in server
    assert "model=self._remember_agent_model(str(body.get('model') or ''))" in server
    assert 'model=getattr(owner, "_last_agent_model", "") or ""' in server
    assert 'model="",' not in server.split("def answer_open_question")[1].split("answered = dict(payload)")[0]


SEE = [{"role": "user", "content": [
    {"type": "text", "text": "what is this"},
    {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw0KGgo="}},
]}]


def test_a_message_with_an_image_part_reaches_openrouter_whole():
    """The vision card sends text plus an image; the OpenAI shape every
    non-ollama family speaks carries both as parts, untouched."""
    wire = _Wire(_openai_answer("a plan with four rooms"))
    out = route_chat("deepseek/deepseek-r1", SEE, opener=wire,
                     environ={"OPENROUTER_API_KEY": "or-live"},
                     secrets_loader=lambda name: "")
    assert out["text"] == "a plan with four rooms"
    sent = wire.body["messages"][0]["content"]
    assert isinstance(sent, list) and sent[0] == {"type": "text", "text": "what is this"}
    assert sent[1]["type"] == "image_url" and sent[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_an_ollama_route_refuses_an_image_by_name():
    wire = _Wire(_openai_answer("never asked"))
    with pytest.raises(ModelRouteRefused) as refused:
        route_chat("ollama/llama3.3:70b", SEE, opener=wire, environ={},
                   secrets_loader=lambda name: "")
    assert "ollama route cannot carry an image" in str(refused.value)
    assert wire.sent == [], "nothing left the machine"


def test_a_part_that_is_neither_text_nor_image_is_refused():
    with pytest.raises(ModelRouteRefused):
        route_chat("deepseek/deepseek-r1", [{"role": "user", "content": [{"type": "audio"}]}],
                   opener=_Wire(_openai_answer("x")), environ={"OPENROUTER_API_KEY": "k"},
                   secrets_loader=lambda name: "")


def test_a_streamed_answer_is_read_whole_and_a_refusal_carries_its_body():
    """The founder's cloud always streams (proxy.py: Server-Sent Events)."""
    LF = chr(10)
    chunks = (LF + LF).join([
        "data: " + json.dumps({"choices": [{"delta": {"content": "two "}}]}),
        "data: " + json.dumps({"choices": [{"delta": {"content": "walls"}, "finish_reason": "stop"}]}),
        "data: [DONE]",
    ]).encode("utf-8")
    sent = []

    def opener(request, timeout=None):
        sent.append(request)
        return _Answer(chunks)

    out = route_chat("cloud/anthropic/claude-sonnet-5", ASK, opener=opener,
                     environ={}, secrets_loader=lambda name: "",
                     cloud_session={"token": "ah_" + "x" * 40, "base_url": "https://api.archhub.io"})
    assert out["text"] == "two walls" and len(sent) == 1

    class _Refusing:
        def __call__(self, request, timeout=None):
            raise urllib.error.HTTPError(request.full_url, 400, "Bad Request", {}, io.BytesIO(b'{"error":"model has no vision"}'))

    with pytest.raises(ModelRouteRefused) as refused:
        route_chat("deepseek/deepseek-r1", ASK, opener=_Refusing(), environ={"OPENROUTER_API_KEY": "k"}, secrets_loader=lambda name: "")
    assert "HTTP 400" in str(refused.value) and "model has no vision" in str(refused.value)
