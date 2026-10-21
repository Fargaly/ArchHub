"""Court: a fresh machine with no usable model route says so, and names the way out.

Audit 2026-09-28: on a fresh install OpenRouter refused ("No OpenRouter key"), the cloud
refused ("No ArchHub cloud session"), default_composer_route answered ('', ''), and
nothing on screen said why Chat and the Brain looked silent. The model listing now
carries one readiness answer the Studio shows in Chat and on the Brain line.
Review 2026-09-28: the answer is plain copy a person can act on (never an environment
variable name), an unsupported route is its own state, and the per-provider states
travel with it so the Studio can judge the route it actually shows (a node's pick too).
No network, no real key, no cloud session: every source is a fixture.
"""
import json
from types import SimpleNamespace

from nodelang import model_router
from nodelang.application_server import ApplicationServer

_JARGON = ("OPENROUTER_API_KEY", "ARCHHUB_CLOUD_TOKEN", "secrets store", "cloud/,")


def _readiness(route, *, stored=None, session=None, local=None):
    stored = stored or {}
    return model_router.composer_readiness(
        route, environ={}, secrets_loader=lambda name: stored.get(name, ""),
        cloud_session=session, local_states=local)


def _plain(answer):
    text = json.dumps(answer)
    for word in _JARGON:
        assert word not in text, word


def test_no_route_is_an_explicit_no_model_state_with_both_ways_out():
    state = _readiness("")
    assert state["state"] == "no_model"
    assert state["actions"] == ["sign_in", "choose_model"]
    assert "sign in" in state["message"].lower() and "choose" in state["message"].lower()
    _plain(state)


def test_a_picked_route_without_its_key_says_what_to_do_in_plain_words():
    openrouter = _readiness("openrouter/vendor/model")
    assert openrouter["state"] == "no_key"
    assert openrouter["route"] == "openrouter/vendor/model"
    assert "Settings" in openrouter["message"] and "Providers" in openrouter["message"]
    assert "choose_model" in openrouter["actions"] and "sign_in" in openrouter["actions"]
    cloud = _readiness("cloud/archhub-free")
    assert cloud["state"] == "no_key" and cloud["actions"][0] == "sign_in"
    assert "sign in" in cloud["message"].lower()
    _plain(openrouter)
    _plain(cloud)


def test_an_unsupported_route_is_its_own_state_not_no_model():
    for route in ("anthropic/claude-sonnet-5", "not a route", "ollama/"):
        state = _readiness(route)
        assert state["state"] == "invalid", route
        assert state["route"] == route
        assert state["actions"] == ["choose_model"]
        assert "choose another model" in state["message"].lower()
        _plain(state)


def test_a_local_runtime_that_is_not_running_is_unavailable():
    state = _readiness("lmstudio/qwen", local={1234: False, 11434: True})
    assert state["state"] == "unavailable" and "LM Studio" in state["message"]
    assert _readiness("ollama/llama3", local={1234: False, 11434: True})["state"] == "ready"
    assert _readiness("ollama/llama3")["state"] == "ready", "unprobed is never a guess"


def test_a_keyed_or_local_route_is_ready_and_a_signed_in_cloud_is_ready():
    assert _readiness("openrouter/vendor/model", stored={"openrouter": "k"})["state"] == "ready"
    assert _readiness("cloud/archhub-free", session={"token": "t"})["state"] == "ready"


def test_the_provider_states_travel_with_the_answer():
    families = _readiness("", stored={"openrouter": "k"}, local={1234: False, 11434: True})["families"]
    assert families["openrouter"]["state"] == "ready"
    assert families["cloud"]["state"] == "no_key"
    assert families["lmstudio"]["state"] == "unavailable"
    assert families["ollama"]["state"] == "ready"
    _plain(families)


def test_the_model_listing_carries_the_readiness_the_studio_shows(monkeypatch, tmp_path):
    from nodelang import cloud_relay, model_catalogue
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("ARCHHUB_CLOUD_TOKEN", raising=False)
    monkeypatch.setattr(cloud_relay, "load_cloud_session", lambda _: None)
    monkeypatch.setattr(model_catalogue, "held_model_groups", lambda session: None)
    monkeypatch.setattr(model_catalogue, "live_model_groups", lambda session=None, **kw: {
        "ok": True, "live": True, "count": 0, "source_errors": {}, "groups": []})
    monkeypatch.setattr(model_router, "founder_secrets_key", lambda name: "")
    owner = SimpleNamespace(_read_agent_model=lambda: "", _default_agent_model=lambda: ("", ""),
                            _local_runtime_states=lambda: {1234: False, 11434: False})
    listing = ApplicationServer._project_model_discovery(owner, "/api/universal/models")
    assert listing["readiness"]["state"] == "no_model"
    assert listing["readiness"]["actions"] == ["sign_in", "choose_model"]
    assert listing["readiness"]["families"]["lmstudio"]["state"] == "unavailable"


# ── Fix v3: the ONLY auto-default is openrouter/free, and it is proven free at the
# DISPATCH seam (route_chat free_only), not from a ready token. Cloud is never
# auto-defaulted (a ready token is not a free-billing contract; a hosted actor is
# metered). An installed CLI is never a signed-in subscription. This module courts the
# real default/readiness/dispatch seam, so it overrides conftest's autouse stub.
import pytest as _pytest

from nodelang.model_router import ModelRouteRefused


@_pytest.fixture(autouse=True)
def no_configured_model_default():
    yield


def _rr(route, *, environ=None, secrets_loader=None, cloud_session=None, local_states=None):
    return model_router.composer_readiness(
        route, environ=environ or {}, secrets_loader=secrets_loader or (lambda n: ""),
        cloud_session=cloud_session, local_states=local_states if local_states is not None else {})


def test_openrouter_free_is_the_only_auto_default_when_ready():
    route, source = model_router.admissible_default_route(
        lambda r: {"state": "ready"} if r == "openrouter/free" else {"state": "no_key"})
    assert route == "openrouter/free" and source == "free · OpenRouter"


def test_a_ready_cloud_token_is_never_auto_defaulted():
    # Even with a cloud session that makes cloud/archhub-free "ready", it is not picked:
    # readiness is not a free-billing contract.
    route, source = model_router.admissible_default_route(
        lambda r: _rr(r, cloud_session={"token": "t"}))
    assert (route, source) == ("", ""), (route, source)


def test_an_installed_cli_is_never_auto_defaulted():
    model_router.bind_local_cli_broker(None)
    assert _rr("local-cli/claude")["state"] == "ready"      # installed-only trap
    assert model_router.admissible_default_route(_rr) == ("", "")


def test_nothing_ready_is_honest_empty():
    assert model_router.admissible_default_route(lambda r: {"state": "no_key"}) == ("", "")


# ── The DISPATCH/billing seam itself (not readiness fixtures). ──
def test_route_chat_free_only_refuses_cloud_before_any_charge():
    with _pytest.raises(ModelRouteRefused, match="Free-only requests require"):
        model_router.route_chat("cloud/archhub-free", [{"role": "user", "content": "hi"}],
                                free_only=True)


def test_route_chat_free_only_refuses_a_paid_model():
    with _pytest.raises(ModelRouteRefused, match="Free-only requests require"):
        model_router.route_chat("openrouter/openai/gpt-4o", [{"role": "user", "content": "hi"}],
                                free_only=True)


def test_route_chat_free_only_admits_openrouter_free():
    # openrouter/free passes the free admission (any later failure is NOT the free refusal),
    # so the auto-default dispatches down the enforced-free path.
    try:
        model_router.route_chat("openrouter/free", [{"role": "user", "content": "hi"}],
                                free_only=True, environ={}, secrets_loader=lambda n: "",
                                cloud_session=None, timeout=0.2)
    except ModelRouteRefused as exc:
        assert "Free-only requests require" not in str(exc), exc
    except Exception:
        pass  # a network/credential failure is fine; the free admission was passed

def test_the_composer_dispatches_openrouter_free_as_free_only():
    # Drive the REAL run_clean_agent_conversation. It is the product seam that decides
    # free_only; deleting that flag at its route_chat call turns this RED.
    import threading, types
    import nodelang.clean_agent_conversation as cac
    captured = {}
    admitted = {"node": "n", "scope": "s", "model": "openrouter/free", "revision": 1,
                "definition_revision": "d", "action": "converse", "prompt": ""}

    def fake_resolve(authority, caller, projection, node_root, *, scope_root, model=None):
        return dict(admitted)

    def fake_route_chat(route, messages, **kw):
        captured["route"] = route
        captured["free_only"] = kw.get("free_only")
        return {"ok": True, "text": "ok", "actual_model": route, "provider": "openrouter", "family": "openrouter"}

    class Owner:
        _mutation_lock = threading.Lock()
        clean_authority = types.SimpleNamespace(store=types.SimpleNamespace(revision=1))
        clean_caller = object()
        def _standing_scope(self, binding, *, expected_scope=None):
            return "s"
        def _canvas(self, binding, *, scope_root):
            return {}

    held_resolve, held_route = cac.resolve_clean_node_model_route, cac.route_chat
    cac.resolve_clean_node_model_route = fake_resolve
    cac.route_chat = fake_route_chat
    try:
        out = cac.run_clean_agent_conversation(Owner(), {}, {"node": "n", "prompt": "hi"}, revalidate=lambda: None)
    finally:
        cac.resolve_clean_node_model_route, cac.route_chat = held_resolve, held_route
    assert captured.get("route") == "openrouter/free"
    assert captured.get("free_only") is True, "the composer must dispatch the free default free_only=True"
    assert out.get("ok") is True
