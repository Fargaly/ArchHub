"""The model picker shows what exists, read live -- not a list typed in 2025.

2026-09-05 the founder opened the picker (Claude Sonnet 4.5 / Opus 4.1 / GPT-4o
/ two OpenRouter rows) and asked "are these really all that exist?"."""
from __future__ import annotations

import io
import json
from pathlib import Path

from nodelang import model_catalogue as mc

ROOT = Path(__file__).resolve().parents[2]


class _Answer(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _opener(routes):
    def open_(request, timeout):
        url = request.full_url
        for key, payload in routes.items():
            if key in url:
                if isinstance(payload, Exception):
                    raise payload
                return _Answer(json.dumps(payload).encode("utf-8"))
        raise OSError("unreachable " + url)
    return open_


def test_groups_come_from_the_free_live_sources_with_real_state(monkeypatch):
    mc.reset_cache()
    monkeypatch.setattr(mc, "subscription_cli_models", lambda: [
        {"name": "Codex", "route": "local-cli/codex", "vendor": "Codex",
         "tag": "SUBSCRIPTION", "ctx": "", "cost": "subscription app",
         "state": "installed", "readiness": "installed and signed in", "col": "#3fb950"}
    ])
    opener = _opener({
        "api.archhub.io/v1/models": {"data": [{"id": "anthropic/claude-sonnet-5", "owned_by": "anthropic", "context_length": 200000}]},
        "openrouter.ai": {"data": [
            {"id": "inclusionai/ling-3.1-flash", "name": "Ling 3.1 Flash", "context_length": 131072, "pricing": {"prompt": "0", "completion": "0"}},
            {"id": "google/lyria-3-clip-preview", "name": "Lyria", "pricing": {"prompt": "0", "completion": "0"}, "architecture": {"output_modalities": ["audio"]}},
            {"id": "nvidia/nemotron-3.5-content-safety", "name": "Safety", "pricing": {"prompt": "0", "completion": "0"}},
            {"id": "deepseek/deepseek-r1", "name": "DeepSeek R1", "context_length": 131072, "pricing": {"prompt": "0.00000055", "completion": "0.0000022"}},
        ]},
        "127.0.0.1:1234": {"data": [{"id": "qwen2.5-coder-7b"}]},
        "127.0.0.1:11434": OSError("no ollama"),
    })
    out = mc.live_model_groups({"token": "t", "base_url": "https://api.archhub.io"}, opener=opener, now=1000.0)
    names = [g["name"] for g in out["groups"]]
    assert names == ["Free cloud (OpenRouter)", "This machine (LM Studio / Ollama)", "Your apps (subscription)"]
    byo, local, apps = out["groups"]
    assert [i["route"] for i in byo["items"]] == ["inclusionai/ling-3.1-flash"]
    assert byo["items"][0]["cost"] == "free" and byo["items"][0]["ctx"] == "131k"
    assert local["items"] == [{"name": "qwen2.5-coder-7b", "route": "lmstudio/qwen2.5-coder-7b", "vendor": "LM Studio",
                               "tag": "LOCAL", "ctx": "", "cost": "free · local", "col": "#3fb950"}]
    assert apps["items"][0]["route"] == "local-cli/codex" and apps["items"][0]["state"] == "installed"
    assert out["count"] == 3 and out["source_errors"] == {}
    # cached: a second read inside ten minutes does not touch the network
    again = mc.live_model_groups({"token": "t", "base_url": "https://api.archhub.io"}, opener=_opener({}), now=1100.0)
    assert again == out and again is not out


def test_a_silent_source_is_named_never_invented(monkeypatch):
    mc.reset_cache()
    monkeypatch.setattr(mc, "subscription_cli_models", lambda: [])
    out = mc.live_model_groups(None, opener=_opener({}), now=5000.0)
    assert out["groups"] == [] and out["count"] == 0
    assert "Free cloud (OpenRouter)" in out["source_errors"]


def test_openrouter_free_routes_require_numeric_zero_pricing_fields():
    payload = {"groups": [{"name": mc.BYO_GROUP, "items": [
        {"route": "vendor/display-only:free", "tag": "BYO", "cost": "$0 / $0 per M"},
        {"route": "vendor/request-cost:free", "tag": "BYO", "prompt_price_per_m": 0.0,
         "completion_price_per_m": 0.0, "request_price": 0.01},
        {"route": "vendor/image-cost:free", "tag": "BYO", "prompt_price_per_m": 0.0,
         "completion_price_per_m": 0.0, "image_price": 0.01},
        {"route": "vendor/strict-free:free", "tag": "BYO", "prompt_price_per_m": 0.0,
         "completion_price_per_m": 0.0, "request_price": 0.0, "image_price": 0.0, "all_prices_zero": True},
        {"route": "vendor/no-request-image:free", "tag": "BYO", "prompt_price_per_m": 0.0,
         "completion_price_per_m": 0.0, "all_prices_zero": True},
        # Another pricing field OpenRouter sent (e.g. web_search) is not zero: never free.
        {"route": "vendor/other-field-cost:free", "tag": "BYO", "prompt_price_per_m": 0.0,
         "completion_price_per_m": 0.0, "all_prices_zero": False},
    ]}]}
    assert mc.openrouter_free_chat_routes(payload) == (
        "vendor/display-only:free", "vendor/strict-free:free", "vendor/no-request-image:free")


def test_default_route_display_row_uses_catalogue_then_server_fallback():
    payload = mc.groups_with_routes({"groups": [{"name": mc.BYO_GROUP, "items": [{
        "name": "OpenRouter catalogue name",
        "route": "openrouter/free",
        "vendor": "OpenRouter",
        "tag": "BYO",
        "col": "#123456",
    }]}]})
    row = mc.default_route_display_row(payload, "openrouter/free", "free · OpenRouter")
    assert row["name"] == "OpenRouter catalogue name"
    assert row["route"] == "openrouter/free"
    assert row["routed"] == "openrouter/free"

    fallback = mc.default_route_display_row({"groups": []}, "openrouter/free", "free · OpenRouter")
    assert fallback["name"] == "Free Models Router"
    assert fallback["route"] == "openrouter/free"
    assert fallback["routed"] == "openrouter/free"


def test_every_openrouter_pricing_field_must_be_zero_for_all_prices_zero():
    rows = {"data": [
        {"id": "a/strict:free", "pricing": {"prompt": "0", "completion": "0", "request": "0", "image": "0",
                                            "web_search": "0", "internal_reasoning": "0"}},
        {"id": "b/search-cost:free", "pricing": {"prompt": "0", "completion": "0", "web_search": "0.004"}},
        {"id": "c/no-pricing:free"},
        {"id": "d/boolean-price:free", "pricing": {"prompt": False, "completion": "0"}},
    ]}
    import json as _json, io as _io

    class _Ans(_io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *exc): return False

    items = mc.openrouter_models(opener=lambda req, timeout=None: _Ans(_json.dumps(rows).encode()), timeout=1)
    flags = {item["route"]: item["all_prices_zero"] for item in items}
    assert flags == {"a/strict:free": True, "c/no-pricing:free": False,
                     "d/boolean-price:free": False}


def test_subscription_cli_rows_show_only_installed_apps_with_state():
    rows = mc.subscription_cli_models(cli_rows=[
        {"id": "claude-code", "name": "Claude Code", "state": "installed",
         "source": "installed on this machine; signed in"},
        {"id": "codex", "name": "Codex", "state": "not installed",
         "source": "not found on PATH"},
    ])
    assert rows == [{
        "name": "Claude Code", "route": "local-cli/claude", "vendor": "Claude Code",
        "tag": "SUBSCRIPTION", "ctx": "", "cost": "subscription app",
        "state": "installed", "readiness": "installed on this machine; signed in",
        "col": "#3fb950",
    }]


def test_the_route_and_the_picker_are_wired():
    server = (ROOT / "01.APP/nodelang" / "application_server.py").read_text(encoding="utf-8")
    assert "'/api/universal/models'" in server and "live_model_groups(session)" in server
    app = (ROOT / "01.APP/nodelang" / "universal_application.py").read_text(encoding="utf-8")
    assert '("GET", "/api/universal/models", "read")' in app
    jsx = (ROOT / "01.APP/nodelang" / "studio" / "studio-lm.jsx").read_text(encoding="utf-8")
    assert "fetch('/api/universal/models'" in jsx
    assert "Showing the list last discovered" in jsx
    assert "OFFLINE LIST" not in jsx
