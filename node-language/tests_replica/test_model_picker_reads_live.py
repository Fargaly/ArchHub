"""The model picker shows what exists, read live -- not a list typed in 2025.

2026-09-05 the founder opened the picker (Claude Sonnet 4.5 / Opus 4.1 / GPT-4o
/ two OpenRouter rows) and asked "are these really all that exist?"."""
from __future__ import annotations

import io
import json
from pathlib import Path

from nodelang import model_catalogue as mc

ROOT = Path(__file__).resolve().parents[1]


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


def test_groups_come_from_the_three_live_sources_with_real_prices():
    mc.reset_cache()
    opener = _opener({
        "api.archhub.io/v1/models": {"data": [{"id": "anthropic/claude-sonnet-5", "owned_by": "anthropic", "context_length": 200000}]},
        "openrouter.ai": {"data": [
            {"id": "deepseek/deepseek-r1", "name": "DeepSeek R1", "context_length": 131072, "pricing": {"prompt": "0.00000055", "completion": "0.0000022"}},
            {"id": "meta-llama/llama-3.3-70b-instruct", "name": "Llama 3.3 70B", "context_length": 131072, "pricing": {"prompt": "0.00000012", "completion": "0.0000003"}},
        ]},
        "127.0.0.1:1234": {"data": [{"id": "qwen2.5-coder-7b"}]},
        "127.0.0.1:11434": OSError("no ollama"),
    })
    out = mc.live_model_groups({"token": "t", "base_url": "https://api.archhub.io"}, opener=opener, now=1000.0)
    names = [g["name"] for g in out["groups"]]
    assert names == ["CLOUD · subscription", "BYO · OpenRouter", "LOCAL · this machine"]
    cloud, byo, local = out["groups"]
    assert cloud["items"][0] == {"name": "anthropic/claude-sonnet-5", "route": "anthropic/claude-sonnet-5", "vendor": "anthropic",
                                 "tag": "CLOUD", "ctx": "200k", "cost": "subscription", "col": "#cc785c"}
    r1 = next(i for i in byo["items"] if i["route"] == "deepseek/deepseek-r1")
    assert r1["cost"] == "$0.55 / $2.20 per M" and r1["ctx"] == "131k" and r1["tag"] == "BYO"
    assert local["items"] == [{"name": "qwen2.5-coder-7b", "route": "lmstudio/qwen2.5-coder-7b", "vendor": "LM Studio",
                               "tag": "LOCAL", "ctx": "", "cost": "free · local", "col": "#3fb950"}]
    assert out["count"] == 4 and out["source_errors"] == {}
    # cached: a second read inside ten minutes does not touch the network
    again = mc.live_model_groups({"token": "t", "base_url": "https://api.archhub.io"}, opener=_opener({}), now=1100.0)
    assert again is out


def test_a_silent_source_is_named_never_invented():
    mc.reset_cache()
    out = mc.live_model_groups(None, opener=_opener({}), now=5000.0)
    assert out["groups"] == [] and out["count"] == 0
    assert "BYO · OpenRouter" in out["source_errors"]


def test_the_route_and_the_picker_are_wired():
    server = (ROOT / "nodelang" / "application_server.py").read_text(encoding="utf-8")
    assert "'/api/universal/models'" in server and "live_model_groups(session)" in server
    app = (ROOT / "nodelang" / "universal_application.py").read_text(encoding="utf-8")
    assert '("GET", "/api/universal/models", "read")' in app
    jsx = (ROOT / "nodelang" / "studio" / "studio-lm.jsx").read_text(encoding="utf-8")
    assert "fetch('/api/universal/models'" in jsx and "'LIVE · '" in jsx and "OFFLINE LIST" in jsx
