"""OpenRouter FREE-FOR-ALL — the founder's one key serves :free models to all.

Founder #64 (2026-06-22): OPENROUTER_API_KEY is staged on archhub-cloud so the
cloud free default serves OpenRouter `:free` models to EVERY signed-in user with
no BYO key + no paid plan. OpenRouter is already half-wired (config defaults +
proxy headers); these tests prove the rest is real:

  - config.select_free_model() returns the OpenRouter free model + base when
    ONLY OPENROUTER_API_KEY is set (the founder's key), and OpenRouter is
    PREFERRED over NVIDIA/Gemini when its key is present.
  - The curated `:free` rotation pool is exposed in order via
    config.free_model_rotation().
  - proxy._stream_free streams the OpenRouter free model AND rotates to the next
    pool model on a simulated 429 / 4xx (shared-key budget resilience).
  - The user-facing free path is SERVED (no 402) and advertises the OpenRouter
    free model on /v1/models.
  - The per-user daily free cap returns an honest 402 free_daily_cap over the
    cap (shared founder key not exhausted by one user).
  - The free path consumes NO hosted credit (free is free).
  - NVIDIA/Gemini still win when OpenRouter is NOT keyed (no regression).
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException
from fastapi.responses import StreamingResponse


@pytest.fixture(autouse=True)
def _fresh_db(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", str(tmp_path / "t.db"))
    import importlib
    import config as _config
    import db as _db
    import proxy as _proxy
    importlib.reload(_config)
    importlib.reload(_db)
    importlib.reload(_proxy)
    _db.init_schema()
    yield


def _user(email: str, plan: str = "trial"):
    import db
    u = db.get_or_create_user(email)
    if plan != "trial":
        db.update_user_plan(u["id"], plan=plan, stripe_id=None, period_end=None)
        u = db.get_user_by_email(email)
    return u


def _reset_free_env(monkeypatch):
    """Clean slate: free ON, every provider key cleared, committed defaults."""
    monkeypatch.setattr("config.FREE_DEFAULT_ENABLED", True)
    monkeypatch.setattr("config.FREE_PROVIDER", "nvidia")
    monkeypatch.setattr("config.FREE_PROVIDER_API_KEY", "")
    monkeypatch.setattr("config.FREE_PROVIDER_BASE_URL", "")
    monkeypatch.setattr("config.ARCHHUB_FREE_MODEL",
                        "meta/llama-3.3-70b-instruct")
    monkeypatch.setattr("config.NVIDIA_API_KEY", "")
    monkeypatch.setattr("config.NVIDIA_BASE_URL",
                        "https://integrate.api.nvidia.com/v1")
    monkeypatch.setattr("config.NVIDIA_MODEL", "meta/llama-3.3-70b-instruct")
    monkeypatch.setattr("config.GOOGLE_API_KEY", "")
    monkeypatch.setattr("config.OPENROUTER_API_KEY", "")
    monkeypatch.setattr("config.OPENROUTER_BASE_URL",
                        "https://openrouter.ai/api/v1")
    monkeypatch.setattr("config.OPENROUTER_MODEL",
                        "meta-llama/llama-3.3-70b-instruct:free")
    monkeypatch.setattr("config.OPENROUTER_FREE_MODELS", (
        "meta-llama/llama-3.3-70b-instruct:free",
        "deepseek/deepseek-chat-v3-0324:free",
        "qwen/qwen-2.5-72b-instruct:free",
    ))
    monkeypatch.setattr("config.FREE_DAILY_CAP_PER_USER", 200)


def _call(user, body=None):
    import proxy
    return asyncio.run(
        proxy.chat_completions(user=user, body=body or {"model": "auto"}))


async def _drain(resp):
    async for _ in resp.body_iterator:
        pass


async def _agen(*chunks):
    for c in chunks:
        yield c


# ── select_free_model: OpenRouter when only OPENROUTER_API_KEY ───────

def test_select_openrouter_when_only_openrouter_key(monkeypatch):
    import config
    _reset_free_env(monkeypatch)
    monkeypatch.setattr("config.OPENROUTER_API_KEY", "or-founder-key")
    sel = config.select_free_model()
    assert sel is not None
    assert sel["provider"] == "openrouter"
    assert sel["base_url"] == "https://openrouter.ai/api/v1"
    assert sel["model"] == "meta-llama/llama-3.3-70b-instruct:free"
    assert sel["key"] == "or-founder-key"
    assert config.free_default_available() is True
    assert config.free_provider_key() == "or-founder-key"
    assert config.free_selected_model() == (
        "meta-llama/llama-3.3-70b-instruct:free")


def test_openrouter_preferred_over_nvidia_and_gemini(monkeypatch):
    """The founder's OpenRouter key leads the chain — NVIDIA + Gemini are
    alternates when it's present."""
    import config
    _reset_free_env(monkeypatch)
    monkeypatch.setattr("config.OPENROUTER_API_KEY", "or-key")
    monkeypatch.setattr("config.NVIDIA_API_KEY", "nv-key")
    monkeypatch.setattr("config.GOOGLE_API_KEY", "g-key")
    assert config.select_free_model()["provider"] == "openrouter"


def test_nvidia_still_wins_when_openrouter_absent(monkeypatch):
    """No regression: with OpenRouter unkeyed, NVIDIA wins as before."""
    import config
    _reset_free_env(monkeypatch)
    monkeypatch.setattr("config.NVIDIA_API_KEY", "nv-key")
    monkeypatch.setattr("config.GOOGLE_API_KEY", "g-key")
    assert config.select_free_model()["provider"] == "nvidia"


def test_gemini_still_wins_when_only_google(monkeypatch):
    import config
    _reset_free_env(monkeypatch)
    monkeypatch.setattr("config.GOOGLE_API_KEY", "g-key")
    assert config.select_free_model()["provider"] == "google"


# ── rotation pool ────────────────────────────────────────────────────

def test_free_model_rotation_lists_openrouter_pool_in_order(monkeypatch):
    import config
    _reset_free_env(monkeypatch)
    monkeypatch.setattr("config.OPENROUTER_API_KEY", "or-key")
    rot = config.free_model_rotation()
    models = [c["model"] for c in rot]
    assert models == [
        "meta-llama/llama-3.3-70b-instruct:free",
        "deepseek/deepseek-chat-v3-0324:free",
        "qwen/qwen-2.5-72b-instruct:free",
    ]
    # All carry the same server-side key + provider + base.
    assert all(c["provider"] == "openrouter" for c in rot)
    assert all(c["key"] == "or-key" for c in rot)
    assert all(c["base_url"] == "https://openrouter.ai/api/v1" for c in rot)


def test_free_model_rotation_single_for_nvidia(monkeypatch):
    """NVIDIA has no extra free pool — one candidate (existing behaviour)."""
    import config
    _reset_free_env(monkeypatch)
    monkeypatch.setattr("config.NVIDIA_API_KEY", "nv-key")
    rot = config.free_model_rotation()
    assert len(rot) == 1
    assert rot[0]["provider"] == "nvidia"


def test_free_model_rotation_empty_when_nothing_reachable(monkeypatch):
    import config
    _reset_free_env(monkeypatch)
    assert config.free_model_rotation() == []


# ── proxy._stream_free rotates on a simulated 4xx ────────────────────

class _FakeStreamCtx:
    def __init__(self, status_code, model, sink):
        self.status_code = status_code
        self._model = model
        self._sink = sink

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def aiter_bytes(self):
        self._sink.append(("streamed", self._model))
        yield ('data: {"choices":[{"delta":{"content":"%s"}}]}\n\n'
               % self._model).encode()

    async def aread(self):
        self._sink.append(("drained", self._model))
        return b""


def _fake_client_factory(status_by_model, sink):
    class _FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def stream(self, method, url, headers=None, json=None):
            model = (json or {}).get("model")
            sink.append(("request", model, url,
                         (headers or {}).get("Authorization")))
            return _FakeStreamCtx(status_by_model.get(model, 200), model, sink)

    return _FakeClient


def test_stream_free_rotates_to_next_pool_model_on_429(monkeypatch):
    """First OpenRouter free model is 429 (rate-limited) → rotate to the next
    pool model on the SAME key, which streams. The shared key isn't broken by
    one throttled model."""
    import config
    import proxy
    _reset_free_env(monkeypatch)
    monkeypatch.setattr("config.OPENROUTER_API_KEY", "or-key")

    sink = []
    status = {"meta-llama/llama-3.3-70b-instruct:free": 429}
    monkeypatch.setattr(
        proxy.httpx, "AsyncClient",
        _fake_client_factory(status, sink))

    head = config.free_selected_model()
    chunks = asyncio.run(_collect(proxy._stream_free(head, {"model": head})))
    body = b"".join(chunks).decode()
    # The throttled head was drained, the SECOND pool model was streamed.
    assert ("drained", "meta-llama/llama-3.3-70b-instruct:free") in sink
    assert ("streamed", "deepseek/deepseek-chat-v3-0324:free") in sink
    assert "deepseek/deepseek-chat-v3-0324:free" in body
    # Server-side key carried every attempt.
    auths = [s[3] for s in sink if s[0] == "request"]
    assert all(a == "Bearer or-key" for a in auths)


def test_stream_free_first_model_streams_when_ok(monkeypatch):
    """Happy path: head model returns 200 → it streams, no rotation."""
    import config
    import proxy
    _reset_free_env(monkeypatch)
    monkeypatch.setattr("config.OPENROUTER_API_KEY", "or-key")
    sink = []
    monkeypatch.setattr(
        proxy.httpx, "AsyncClient", _fake_client_factory({}, sink))
    head = config.free_selected_model()
    asyncio.run(_collect(proxy._stream_free(head, {"model": head})))
    streamed = [s[1] for s in sink if s[0] == "streamed"]
    assert streamed == ["meta-llama/llama-3.3-70b-instruct:free"]


def test_stream_free_last_candidate_streams_error_body(monkeypatch):
    """Every pool model 4xxes → the LAST upstream (error) body is streamed
    through so the client gets an honest response, not silence."""
    import config
    import proxy
    _reset_free_env(monkeypatch)
    monkeypatch.setattr("config.OPENROUTER_API_KEY", "or-key")
    sink = []
    status = {
        "meta-llama/llama-3.3-70b-instruct:free": 429,
        "deepseek/deepseek-chat-v3-0324:free": 429,
        "qwen/qwen-2.5-72b-instruct:free": 429,
    }
    monkeypatch.setattr(
        proxy.httpx, "AsyncClient", _fake_client_factory(status, sink))
    head = config.free_selected_model()
    asyncio.run(_collect(proxy._stream_free(head, {"model": head})))
    # Last candidate still streamed (honest error body), earlier ones drained.
    assert ("streamed", "qwen/qwen-2.5-72b-instruct:free") in sink


async def _collect(agen):
    out = []
    async for c in agen:
        out.append(c)
    return out


# ── user-facing: served free + /v1/models advertises OpenRouter ──────

def test_no_key_user_served_openrouter_free_not_402(monkeypatch):
    import config
    import proxy
    _reset_free_env(monkeypatch)
    monkeypatch.setattr("config.OPENROUTER_API_KEY", "or-key")
    monkeypatch.setattr("proxy._stream_free",
                        lambda m, b: _agen(b'data: {}\n\n'))
    resp = _call(_user("oruser@example.com", "trial"))
    assert isinstance(resp, StreamingResponse)
    assert resp.headers.get("X-ArchHub-Tier") == "free-default"
    assert resp.headers.get("X-ArchHub-Model") == (
        "meta-llama/llama-3.3-70b-instruct:free")


def test_models_advertises_openrouter_free_default(monkeypatch):
    import config
    import proxy
    _reset_free_env(monkeypatch)
    monkeypatch.setattr("config.OPENROUTER_API_KEY", "or-key")
    out = proxy.list_models(user=_user("orm@example.com", "trial"))
    assert out["archhub_free_default"] is True
    assert out["archhub_default_model"] == (
        "meta-llama/llama-3.3-70b-instruct:free")
    ids = [m["id"] for m in out["data"]]
    assert "meta-llama/llama-3.3-70b-instruct:free" in ids


def test_free_path_consumes_no_hosted_credit(monkeypatch):
    """Free is free: bumps the fair-use counter, never a hosted credit."""
    import config
    import db
    import proxy
    _reset_free_env(monkeypatch)
    monkeypatch.setattr("config.OPENROUTER_API_KEY", "or-key")
    calls = {"credit": 0, "usage": 0}
    monkeypatch.setattr(
        "db.consume_credit_for_actor",
        lambda u, n: calls.__setitem__("credit", calls["credit"] + n))
    monkeypatch.setattr(
        "db.increment_usage_for_actor",
        lambda u, n: calls.__setitem__("usage", calls["usage"] + n))
    monkeypatch.setattr("proxy._stream_free",
                        lambda m, b: _agen(b'data: {}\n\n'))
    resp = _call(_user("orcredit@example.com", "trial"))
    asyncio.run(_drain(resp))
    assert calls["credit"] == 0
    assert calls["usage"] == 1


# ── per-user daily free cap ──────────────────────────────────────────

def test_free_daily_cap_blocks_over_limit(monkeypatch):
    """Over the per-user daily free cap → honest 402 free_daily_cap (the
    shared founder key isn't exhausted by one user). Under it → served."""
    import config
    import db
    import proxy
    _reset_free_env(monkeypatch)
    monkeypatch.setattr("config.OPENROUTER_API_KEY", "or-key")
    monkeypatch.setattr("config.FREE_DAILY_CAP_PER_USER", 3)
    u = _user("orcap@example.com", "trial")
    # Seed 3 free turns already used today.
    for _ in range(3):
        db.log_usage(u["id"], model="free:meta-llama/llama-3.3-70b-instruct:free",
                     input_toks=0, output_toks=0, cost_micros=0)
    with pytest.raises(HTTPException) as exc:
        _call(u)
    assert exc.value.status_code == 402
    assert exc.value.detail["error"] == "free_daily_cap"
    assert exc.value.detail["free_daily_cap"] == 3
    assert exc.value.detail["free_used_today"] == 3


def test_free_daily_cap_under_limit_served(monkeypatch):
    import config
    import db
    import proxy
    _reset_free_env(monkeypatch)
    monkeypatch.setattr("config.OPENROUTER_API_KEY", "or-key")
    monkeypatch.setattr("config.FREE_DAILY_CAP_PER_USER", 5)
    monkeypatch.setattr("proxy._stream_free",
                        lambda m, b: _agen(b'data: {}\n\n'))
    u = _user("orunder@example.com", "trial")
    db.log_usage(u["id"], model="free:x", input_toks=0, output_toks=0,
                 cost_micros=0)
    resp = _call(u)
    assert isinstance(resp, StreamingResponse)


def test_free_daily_cap_disabled_when_zero(monkeypatch):
    import config
    import db
    import proxy
    _reset_free_env(monkeypatch)
    monkeypatch.setattr("config.OPENROUTER_API_KEY", "or-key")
    monkeypatch.setattr("config.FREE_DAILY_CAP_PER_USER", 0)  # unlimited
    monkeypatch.setattr("proxy._stream_free",
                        lambda m, b: _agen(b'data: {}\n\n'))
    u = _user("oruncap@example.com", "trial")
    for _ in range(50):
        db.log_usage(u["id"], model="free:x", input_toks=0, output_toks=0,
                     cost_micros=0)
    resp = _call(u)
    assert isinstance(resp, StreamingResponse)


def test_free_messages_today_counts_only_free_rows(monkeypatch):
    """The cap meters ONLY free turns — hosted/BYO usage rows don't count."""
    import db
    u = _user("orcount@example.com", "trial")
    db.log_usage(u["id"], model="free:a", input_toks=0, output_toks=0,
                 cost_micros=0)
    db.log_usage(u["id"], model="free:b", input_toks=0, output_toks=0,
                 cost_micros=0)
    db.log_usage(u["id"], model="gpt-4o", input_toks=0, output_toks=0,
                 cost_micros=0)  # hosted — must NOT count
    assert db.free_messages_today(u["id"]) == 2
