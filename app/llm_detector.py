"""LLM auto-detection — probes every LLM backend ArchHub knows about.

Called at app boot + every 30s by the header pill refresh. Cheap probes
only (filesystem + localhost HTTP) — no paid API calls.

Returns a dict per provider with:
    status:  "live"     — configured + reachable + has model(s) available
             "available" — configured but inactive (process not running,
                            no models loaded, quota exceeded, etc.)
             "missing"  — no key / binary / install
    models:    list[str]   — model ids the provider exposes (empty if N/A)
    note:      str          — one-line human reason (for tooltip)
    detail:    dict          — extra debug info (binary path, URL, etc.)

The chat header consumes this to draw the provider pills. The agents
daemon's backend selector consumes the same to decide which backend
to default to.
"""
from __future__ import annotations

import json
import os
import socket
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

# Cheap per-process cache so the 30s refresh doesn't re-probe inside
# the same Qt tick.
_CACHE: dict[str, tuple[float, dict]] = {}
_CACHE_TTL_SECONDS = 25.0


# ---------------------------------------------------------------------------
def _cached(key: str, ttl: float = _CACHE_TTL_SECONDS):
    """Decorator-like helper. `key` is the cache slot."""
    def wrap(fn):
        def inner():
            now = time.time()
            if key in _CACHE:
                ts, val = _CACHE[key]
                if now - ts < ttl:
                    return val
            val = fn()
            _CACHE[key] = (now, val)
            return val
        return inner
    return wrap


def _http_json(url: str, timeout: float = 1.5) -> Optional[dict]:
    """Stdlib GET → JSON. Returns None on any failure."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            if 200 <= resp.status < 300:
                return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None
    return None


def _tcp_open(host: str, port: int, timeout: float = 0.3) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
@_cached("codex_cli")
def probe_codex_cli() -> dict:
    """OpenAI Codex CLI — local Windows binary at ~/.codex/.sandbox-bin/.
    Bypasses the OpenAI API 429 quota wall (separate ChatGPT auth)."""
    home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    bin_path = home / ".sandbox-bin" / "codex.exe"
    auth_path = home / "auth.json"
    if not bin_path.exists():
        return {
            "status":  "missing",
            "models":  [],
            "note":    f"binary not found at {bin_path}",
            "detail":  {"home": str(home), "bin": str(bin_path)},
        }
    if not auth_path.exists():
        return {
            "status":  "available",
            "models":  [],
            "note":    "binary present, not logged in (run `codex login`)",
            "detail":  {"bin": str(bin_path)},
        }
    # Try to read the configured model from config.toml. Fall back to
    # the default Codex variant.
    try:
        toml = (home / "config.toml").read_text(encoding="utf-8", errors="replace")
        configured = None
        for line in toml.splitlines():
            if line.strip().startswith("model"):
                # `model = "gpt-5.5"` style
                if "=" in line:
                    rhs = line.split("=", 1)[1].strip().strip('"').strip("'")
                    configured = rhs
                    break
    except Exception:
        configured = None
    return {
        "status":  "live",
        "models":  [configured or "gpt-5.3-codex"],
        "note":    f"signed in (cli + chatgpt auth); model={configured or 'gpt-5.3-codex'}",
        "detail":  {"bin": str(bin_path), "configured_model": configured},
    }


@_cached("anthropic")
def probe_anthropic() -> dict:
    """Anthropic Claude — check key presence only (no live call)."""
    key = _load_key("anthropic")
    if not key:
        return {
            "status":  "missing",
            "models":  [],
            "note":    "no API key set (Settings → Sign-ins → Anthropic)",
            "detail":  {},
        }
    return {
        "status":  "live",
        "models":  ["claude-haiku-4-5", "claude-sonnet-4-6"],
        "note":    "API key present (live status verified on next call)",
        "detail":  {"key_prefix": key[:8]},
    }


@_cached("openai")
def probe_openai() -> dict:
    """OpenAI — check key presence. Live status decided by router."""
    key = _load_key("openai")
    if not key:
        return {
            "status":  "missing",
            "models":  [],
            "note":    "no API key set",
            "detail":  {},
        }
    return {
        "status":  "live",
        "models":  ["gpt-5.5", "gpt-5.4-mini", "gpt-5.3-codex"],
        "note":    "API key present (may be quota-limited)",
        "detail":  {"key_prefix": key[:8]},
    }


@_cached("google")
def probe_google() -> dict:
    """Google AI / Gemini — key only."""
    key = _load_key("google")
    if not key:
        return {
            "status":  "missing",
            "models":  [],
            "note":    "no API key set",
            "detail":  {},
        }
    return {
        "status":  "live",
        "models":  ["gemini-2.5-flash", "gemini-2.5-pro"],
        "note":    "API key present",
        "detail":  {"key_prefix": key[:8]},
    }


@_cached("openrouter")
def probe_openrouter() -> dict:
    """OpenRouter — one OAuth covers 300+ models."""
    key = _load_key("openrouter")
    if not key:
        return {
            "status":  "missing",
            "models":  [],
            "note":    "no API key set",
            "detail":  {},
        }
    return {
        "status":  "live",
        "models":  ["openrouter/auto", "anthropic/claude-sonnet-4",
                    "google/gemini-2.5-flash"],
        "note":    "OAuth complete (300+ models reachable)",
        "detail":  {"key_prefix": key[:8]},
    }


@_cached("lmstudio")
def probe_lmstudio() -> dict:
    """LM Studio — localhost OpenAI-compatible server."""
    base = os.environ.get("LMSTUDIO_BASE_URL", "http://127.0.0.1:1234/v1")
    base = base.rstrip("/")
    # Quick TCP probe first to avoid a 1.5s HTTP wait when nothing's
    # listening at all.
    host, port = "127.0.0.1", 1234
    if "localhost" in base or "127.0.0.1" in base:
        if not _tcp_open(host, port, timeout=0.3):
            return {
                "status":  "missing",
                "models":  [],
                "note":    "LM Studio server not running on :1234",
                "detail":  {"base_url": base},
            }
    data = _http_json(f"{base}/models", timeout=1.5)
    if not data:
        return {
            "status":  "available",
            "models":  [],
            "note":    "process up but /models returned nothing",
            "detail":  {"base_url": base},
        }
    raw = data.get("data") or []
    models = [m.get("id") for m in raw if m.get("id")]
    chat_models = [m for m in models if "embed" not in m.lower()]
    if not chat_models:
        return {
            "status":  "available",
            "models":  [],
            "note":    "server up but no chat model loaded",
            "detail":  {"base_url": base, "embedding_only": models},
        }
    return {
        "status":  "live",
        "models":  chat_models,
        "note":    f"{len(chat_models)} chat model(s) loaded",
        "detail":  {"base_url": base},
    }


@_cached("ollama")
def probe_ollama() -> dict:
    """Ollama — localhost daemon at :11434."""
    base = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
    base = base.rstrip("/")
    if "localhost" in base or "127.0.0.1" in base:
        if not _tcp_open("127.0.0.1", 11434, timeout=0.3):
            return {
                "status":  "missing",
                "models":  [],
                "note":    "Ollama daemon not running (start `ollama serve`)",
                "detail":  {"base_url": base},
            }
    data = _http_json(f"{base}/api/tags", timeout=1.5)
    if not data:
        return {
            "status":  "available",
            "models":  [],
            "note":    "daemon up but /api/tags returned nothing",
            "detail":  {"base_url": base},
        }
    models = [m.get("name") for m in (data.get("models") or []) if m.get("name")]
    if not models:
        return {
            "status":  "available",
            "models":  [],
            "note":    "daemon up but no models pulled (`ollama pull ...`)",
            "detail":  {"base_url": base},
        }
    return {
        "status":  "live",
        "models":  models,
        "note":    f"{len(models)} model(s) pulled",
        "detail":  {"base_url": base},
    }


@_cached("archhub_cloud")
def probe_archhub_cloud() -> dict:
    """ArchHub Cloud — paid SaaS path (cloud-token sign-in)."""
    key = _load_key("archhub_cloud") or _load_setting("cloud_token")
    if not key:
        return {
            "status":  "missing",
            "models":  [],
            "note":    "not signed in to ArchHub Cloud",
            "detail":  {},
        }
    return {
        "status":  "live",
        "models":  ["claude-via-cloud", "gpt-via-cloud", "gemini-via-cloud"],
        "note":    "signed in to Cloud (LLM proxy ready)",
        "detail":  {},
    }


# ---------------------------------------------------------------------------
def _load_key(name: str) -> Optional[str]:
    try:
        from secrets_store import load_api_key
        v = load_api_key(name)
        return v or None
    except Exception:
        return None


def _load_setting(name: str) -> Optional[str]:
    try:
        from secrets_store import load_setting
        return load_setting(name) or None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Public surface — used by chat_window header + agents backend selector.
PROBERS = {
    "anthropic":     probe_anthropic,
    "openai":        probe_openai,
    "google":        probe_google,
    "openrouter":    probe_openrouter,
    "ollama":        probe_ollama,
    "lmstudio":      probe_lmstudio,
    "codex_cli":     probe_codex_cli,
    "archhub_cloud": probe_archhub_cloud,
}


PROVIDER_DISPLAY = {
    "anthropic":     "Claude",
    "openai":        "GPT",
    "google":        "Gemini",
    "openrouter":    "OpenRouter",
    "ollama":        "Ollama",
    "lmstudio":      "LM Studio",
    "codex_cli":     "Codex",
    "archhub_cloud": "Cloud",
}


def detect_all(*, force: bool = False) -> dict[str, dict]:
    """Probe every backend in PROBERS. Returns a dict keyed by provider id.

    Pass force=True to bust the per-process cache (e.g. user clicked
    Refresh in Settings).
    """
    if force:
        _CACHE.clear()
    return {pid: probe() for pid, probe in PROBERS.items()}


def live_providers() -> list[str]:
    """Convenience: ids of providers currently `status=='live'`."""
    return [pid for pid, info in detect_all().items()
            if info.get("status") == "live"]


def display_label(pid: str) -> str:
    return PROVIDER_DISPLAY.get(pid, pid.title())
