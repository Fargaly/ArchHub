"""The router lists exactly the real providers, from one registry, with live state.

Founder 2026-09-28: every provider working and visible in the router. The
models domain carried two invented providers with invented prices; OpenAI and
Google keys answered 200 but had no route; a nine-character Anthropic
placeholder was shown as "keyed"; the signed-in CLIs had no row. This court
fails if any of that comes back.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from nodelang import model_catalogue, model_router
from nodelang.core import Store
from nodelang.domains import models as models_domain

ROOT = Path(__file__).resolve().parents[1]
PLACEHOLDER = re.compile("provider-" + "fast|provider-" + "deep|Fast " + "provider|Deep " + "provider|model-" + "fast|model-" + "deep")
REAL = "x" * 40
MACHINE_KEYS = {"openrouter": REAL, "openai": REAL, "google": REAL,
                "nvidia": REAL, "anthropic": "123456789"}
CLIS = {"claude": "claude.CMD", "codex": "codex.CMD", "gemini": "gemini.CMD"}


def _rows():
    return model_router.provider_rows(
        environ={}, secrets_loader=lambda name: MACHINE_KEYS.get(name, ""),
        cloud_session={"token": REAL}, local_probe=lambda host, port: True,
        cli_probe=lambda name: CLIS.get(name))


def test_no_placeholder_provider_in_product_source():
    for path in (ROOT / "nodelang").rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="replace")
        assert not PLACEHOLDER.search(text), path
    assert not hasattr(models_domain, "DEFAULT_PROVIDERS")
    assert not hasattr(models_domain, "DEFAULT_MODELS")


def test_the_graph_catalogue_is_the_router_registry():
    catalogue = model_router.provider_catalogue()
    ids = [record["id"] for record in catalogue]
    for family in ("cloud", "openrouter", "openai", "google", "nvidia", "lmstudio", "ollama", "anthropic"):
        assert family in ids, family
    assert not any(PLACEHOLDER.search(json.dumps(record)) for record in catalogue)
    store = Store()
    domain = models_domain.build_models_domain(store, providers=catalogue, models=())
    assert sorted(domain["providers"]) == sorted(ids)
    assert models_domain.route_model(store, domain)["model_id"] is None
    application = (ROOT / "nodelang" / "application.py").read_text(encoding="utf-8")
    assert "build_models_domain(store, providers=provider_catalogue(), models=())" in application


def test_every_configured_provider_has_a_row_and_none_is_invented():
    rows = _rows()
    by = {row["id"]: row for row in rows}
    for row in rows:
        assert not PLACEHOLDER.search(json.dumps(row)), row
    assert by["openrouter"]["state"] == "keyed"
    assert by["cloud"]["state"] == "keyed"
    assert by["openai"]["state"] == "keyed" and by["openai"]["sets"] == "OPENAI_API_KEY"
    assert by["google"]["state"] == "keyed" and by["google"]["sets"] == "GOOGLE_API_KEY"
    assert by["nvidia"]["state"] == "keyed" and by["nvidia"]["sets"] == "NVIDIA_API_KEY"
    assert by["anthropic"]["state"] == "key invalid"
    assert by["anthropic"]["source"] == "key invalid, paste a real key in Settings"
    assert by["lmstudio"]["state"] == "running" and by["ollama"]["state"] == "running"
    # Since local-cli/ (2026-09-29) an installed assistant is a chat route.
    for cli in ("claude-code", "codex", "gemini-cli"):
        assert by[cli]["state"] == "installed", cli
    assert by["opencode"]["state"] == "not installed"
    catalogue_ids = {record["id"] for record in model_router.provider_catalogue()}
    assert catalogue_ids <= set(by), catalogue_ids - set(by)


def test_a_provider_the_machine_lacks_still_has_a_row():
    rows = model_router.provider_rows(
        environ={}, secrets_loader=lambda name: "", cloud_session=None,
        local_probe=lambda host, port: False, cli_probe=lambda name: None)
    ids = {row["id"] for row in rows}
    for family in ("openrouter", "cloud", "openai", "google", "nvidia", "lmstudio", "ollama",
                   "claude-code", "codex", "gemini-cli", "opencode", "anthropic"):
        assert family in ids, family
    assert {record["id"] for record in model_router.provider_catalogue()} <= ids


class _Answer:
    def __init__(self, payload):
        self._raw = json.dumps(payload).encode("utf-8")
        self.headers = {"Content-Type": "application/json"}

    def read(self, *_):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def test_openai_and_google_route_directly_with_their_own_key():
    sent = []

    def opener(request, timeout):
        sent.append(request)
        return _Answer({"model": "m", "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]})

    keys = {"openai": "o" * 40, "google": "g" * 40}
    for route, url, family in (
            ("openai-api/gpt-5-nano", "https://api.openai.com/v1/chat/completions", "openai"),
            ("google-api/gemini-2.5-flash-lite",
             "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions", "google")):
        answer = model_router.route_chat(route, [{"role": "user", "content": "hi"}], opener=opener,
                                         environ={}, secrets_loader=lambda name: keys.get(name, ""),
                                         cloud_session=None)
        request = sent[-1]
        assert answer["family"] == family and request.full_url == url
        assert request.get_header("Authorization") == "Bearer " + keys[family]
        assert json.loads(request.data.decode("utf-8"))["model"] == route.split("/", 1)[1]
    openai_body = json.loads(sent[0].data.decode("utf-8"))
    assert "max_completion_tokens" in openai_body and "temperature" not in openai_body
    # Sealed free OpenRouter requests keep their meaning.
    assert model_router.resolve_model_route("google/gemma-4-31b-it:free").family == "openrouter"


def test_nvidia_routes_directly_with_its_own_key():
    sent = []

    def opener(request, timeout):
        sent.append(request)
        return _Answer({"model": "nvidia/nemotron-3-ultra-550b-a55b",
                        "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]})

    answer = model_router.route_chat(
        "nvidia-api/nvidia/nemotron-3-ultra-550b-a55b",
        [{"role": "user", "content": "hi"}],
        opener=opener,
        environ={},
        secrets_loader=lambda name: REAL if name == "nvidia" else "",
        cloud_session=None,
    )
    request = sent[-1]
    assert answer["family"] == "nvidia"
    assert request.full_url == "https://integrate.api.nvidia.com/v1/chat/completions"
    assert request.get_header("Authorization") == "Bearer " + REAL
    assert json.loads(request.data.decode("utf-8"))["model"] == "nvidia/nemotron-3-ultra-550b-a55b"


def test_the_picker_offers_the_cheapest_text_models_read_from_the_vendor_lists():
    listings = {
        model_catalogue.OPENAI_MODELS: {"data": [{"id": i} for i in (
            "gpt-5-nano", "gpt-4.1-nano", "gpt-4o-mini", "gpt-5", "gpt-image-1", "gpt-4o-mini-tts", "whisper-1")]},
        model_catalogue.GOOGLE_MODELS: {"models": [
            {"name": "models/" + i, "supportedGenerationMethods": ["generateContent"]} for i in (
                "gemini-2.5-flash-lite", "gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.5-flash-image",
                "gemma-4-31b-it")]},
    }
    prices = {"openai/gpt-5-nano": (0.05, 0.4), "openai/gpt-4.1-nano": (0.1, 0.4),
              "openai/gpt-4o-mini": (0.15, 0.6), "openai/gpt-5": (1.25, 10.0), "openai/gpt-image-1": (0.01, 0.01),
              "google/gemini-2.5-flash-lite": (0.1, 0.4), "google/gemini-2.5-flash": (0.3, 2.5),
              "google/gemini-2.5-pro": (1.25, 10.0), "google/gemma-4-31b-it": (0.09, 0.34)}

    def opener(request, timeout):
        return _Answer(listings[request.full_url.split("?")[0]])

    items = model_catalogue.direct_models(opener=opener, timeout=1.0, prices=prices,
                                          secrets_loader=lambda name: "k" * 40)
    routes = [item["route"] for item in items]
    assert routes == ["openai-api/gpt-5-nano", "openai-api/gpt-4.1-nano", "openai-api/gpt-4o-mini",
                      "google-api/gemini-2.5-flash-lite", "google-api/gemini-2.5-flash", "google-api/gemini-2.5-pro"]
    for item in items:
        assert model_catalogue.routable_route(item) == item["route"]
        assert model_router.resolve_model_route(item["route"]).family in ("openai", "google")
