"""FreeFleet — the FREE-ONLY worker router the standing dispatcher uses.

THE MONEY FIREWALL. The standing dispatcher loop runs continuously, claiming
ROMA leaves and handing each to a worker model. The whole point of that loop
is that it must NEVER spend metered API money — the work rides on inference
the founder already pays a FLAT RATE for (the Codex/ChatGPT subscription), a
FREE provider tier (NVIDIA NIM), or a model running locally on this machine.

This module is the single chokepoint that guarantees that. Every worker call
goes through `FreeFleet.run_worker`, which:

  * selects a provider in a fixed FREE-ONLY preference order, and
  * passes the selected name through `assert_free()` — a hard allowlist that
    RAISES on any metered provider (anthropic / openai / google / openrouter /
    dashscope). A metered provider can never be selected, so the loop can never
    bill the founder. cost_usd on every result is exactly 0.0.

Preference order (spec):
  1. **codex_cli** — `codex exec` on the user's flat-rate ChatGPT/Codex
     subscription (no per-token quota). stdin is CLOSED (`< /dev/null`) so the
     headless agent can't block waiting for input.
  2. **nvidia** — NVIDIA NIM free models via the OpenAI-compatible endpoint
     https://integrate.api.nvidia.com/v1, ONLY when a key resolves
     (load_api_key('nvidia') → NVIDIA_API_KEY → op://). Skipped otherwise.
  3. **local** — ollama (http://localhost:11434, /api/chat) or LM Studio
     (http://localhost:1234/v1), whichever is reachable.

ONE-SYSTEM: this EXTENDS the ROMA stack — it is the executor the dispatcher
wires into `roma.run_to_dry` (its `ExecutorFn` calls `run_worker`). It does
not duplicate the router, the court, or the tree; it is the free-only inference
seam those parts were missing. It deliberately mirrors the provider shapes
already proven in `app/llm_router.py` (the nvidia NIM base URL + key
resolution, the codex `exec` invocation, the ollama/LM-Studio local endpoints)
WITHOUT importing the desktop app (the brain daemon must run headless), and
WITHOUT ever constructing a metered client.

Pure-Python, dependency-light (stdlib `urllib` + `subprocess` only). Every seam
to the outside world (the four probes + four runners + the two resolvers) is a
module-level function so tests monkeypatch them and NO real network / subprocess
runs under pytest. Secrets are op://-resolvable — never inlined.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from typing import Optional


# ─────────────────────────── the allowlist (firewall) ──────────────────

# The ONLY providers the fleet may ever select. Free = flat-rate subscription
# (codex_cli), free provider tier (nvidia NIM), or local on-machine inference
# (ollama / lmstudio). "local" is the generic alias used when a local backend
# is reached without distinguishing which one.
FREE_PROVIDERS: frozenset[str] = frozenset(
    {"codex_cli", "nvidia", "ollama", "lmstudio", "local"}
)

# Providers that BILL per token / per call. assert_free REFUSES every one of
# these — selecting any of them is the exact thing this module exists to
# prevent. (Anthropic, OpenAI, Google, OpenRouter aggregator, DashScope.)
METERED_PROVIDERS: frozenset[str] = frozenset(
    {"anthropic", "openai", "google", "openrouter", "dashscope"}
)

# NVIDIA NIM free-tier OpenAI-compatible endpoint (mirrors app/llm_router.py's
# nvidia client base). NOT a paid OpenAI/Anthropic base.
NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
# A small, broadly-available free NIM model — overridable via env for the
# dispatcher. Kept generic so a single key reaches the catalog.
NVIDIA_DEFAULT_MODEL = os.environ.get(
    "FREE_FLEET_NVIDIA_MODEL", "meta/llama-3.3-70b-instruct"
)

# Local endpoints (mirror app/llm_router.py + ollama_client / llm_detector).
OLLAMA_BASE = os.environ.get("OLLAMA_BASE", "http://localhost:11434")
LMSTUDIO_BASE = os.environ.get("LMSTUDIO_BASE", "http://localhost:1234/v1")
OLLAMA_DEFAULT_MODEL = os.environ.get("FREE_FLEET_OLLAMA_MODEL", "llama3.1:8b")

# Probe + codex timeouts kept short so a dead endpoint / hung CLI can never
# wedge the standing loop (mirrors ollama_client's 2s probe + codex 300s cap).
_PROBE_TIMEOUT_S = 2.0
_CODEX_TIMEOUT_S = 300
_HTTP_TIMEOUT_S = 120.0

_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


class MeteredProviderError(RuntimeError):
    """Raised by `assert_free` when a metered provider is about to be used.

    This is the money firewall tripping. It is a hard error on purpose: the
    standing dispatcher must FAIL rather than spend the founder's API credit.
    """


def assert_free(provider: str) -> str:
    """The firewall. Return `provider` iff it is on the FREE allowlist; raise
    `MeteredProviderError` otherwise.

    Fail-CLOSED: an UNKNOWN provider (not in either set) is rejected too — we
    never assume a new provider is free. This is the single function every
    selection path funnels through, so no metered call can slip past."""
    if provider in FREE_PROVIDERS:
        return provider
    if provider in METERED_PROVIDERS:
        raise MeteredProviderError(
            f"refusing metered provider '{provider}': the dispatcher fleet is "
            f"FREE-ONLY (allowed: {sorted(FREE_PROVIDERS)}). This is the money "
            f"firewall — workers must never spend API credit."
        )
    raise MeteredProviderError(
        f"refusing unknown provider '{provider}': not on the free allowlist "
        f"{sorted(FREE_PROVIDERS)} (fail-closed — unknown providers are treated "
        f"as potentially metered)."
    )


# ─────────────────────────── secret resolution (op:// only) ─────────────


def _nvidia_key() -> Optional[str]:
    """Resolve a free NVIDIA NIM key WITHOUT ever inlining it.

    Order (mirrors app/llm_router.py's nvidia branch, headless-safe):
      1. ArchHub desktop `secrets_store.load_api_key('nvidia')` — reachable
         when the app package is importable (added defensively to sys.path,
         exactly like reflexion.detect_real_llm_key). In tests conftest injects
         a fake secrets_store whose load_api_key → None, so this misses cleanly.
      2. NVIDIA_API_KEY env var.
      3. op:// reference in NVIDIA_API_KEY_REF, resolved through the brain's
         secret_resolver (1Password CLI → keyring → env fallback). Secrets are
         references-only per the BRAIN-FIRST mandate.

    Returns the key string, or None when no free key is configured (→ nvidia
    is skipped, never an error)."""
    # 1) ArchHub desktop secret store (keyring / obfuscated file / op:// alias).
    try:  # pragma: no cover - exercised only when ArchHub app is present
        from pathlib import Path

        app_dir = Path(__file__).resolve().parents[3] / "app"
        if app_dir.is_dir() and str(app_dir) not in sys.path:
            sys.path.insert(0, str(app_dir))
        from secrets_store import load_api_key  # type: ignore

        v = (load_api_key("nvidia") or "").strip()
        if v:
            return v
    except Exception:
        pass

    # 2) Plain env var.
    env = (os.environ.get("NVIDIA_API_KEY") or "").strip()
    if env:
        return env

    # 3) op:// reference resolved at call time (never stored resolved).
    ref = (os.environ.get("NVIDIA_API_KEY_REF") or "").strip()
    if ref:
        try:
            from .secret_resolver import resolve_secret

            resolved = (resolve_secret(ref) or "").strip()
            if resolved:
                return resolved
        except Exception:
            pass
    return None


# ─────────────────────────── reachability probes ───────────────────────


def _http_ok(url: str, timeout: float) -> bool:
    """True iff a GET to `url` returns any HTTP response (even 4xx — the
    endpoint is UP). Connection refused / DNS / timeout → False. Used by the
    local probes; the ONLY network seam, monkeypatched in tests."""
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            # any status code means something is listening
            return 200 <= getattr(resp, "status", 200) < 600
    except urllib.error.HTTPError:
        # an HTTP error status still means the server is reachable
        return True
    except Exception:
        return False


def _probe_ollama(timeout: float = _PROBE_TIMEOUT_S) -> bool:
    """Is an Ollama server reachable? Probes /api/tags (the model list, the
    same endpoint app/llm_providers/ollama_client uses)."""
    return _http_ok(f"{OLLAMA_BASE.rstrip('/')}/api/tags", timeout)


def _probe_lmstudio(timeout: float = _PROBE_TIMEOUT_S) -> bool:
    """Is an LM Studio server reachable? Probes /models (its OpenAI-compatible
    model list, the same endpoint llm_detector.probe_lmstudio uses)."""
    return _http_ok(f"{LMSTUDIO_BASE.rstrip('/')}/models", timeout)


def _codex_path() -> Optional[str]:
    """Absolute path to the `codex` binary, or None (mirrors
    app/llm_providers/codex_cli_client.codex_cli_path)."""
    return shutil.which("codex") or shutil.which("codex.cmd")


def _codex_available() -> bool:
    """codex is reachable iff the binary is on PATH — no network probe (it runs
    on the local subscription)."""
    return _codex_path() is not None


# ─────────────────────────── free backend runners ──────────────────────
#
# Each runner takes (prompt, kind) and returns the model's text. They are
# module-level so tests stub them (no real subprocess / network). There are
# DELIBERATELY no _run_anthropic / _run_openai / _run_google runners — the
# fleet has no code path to a metered provider at all.


def _build_prompt(prompt: str, kind: str) -> str:
    """Fold the worker `kind` (a short role hint: plan / analysis / quick / …)
    into the prompt as a one-line preamble. Kept trivial + deterministic so
    every backend gets an identical, auditable prompt."""
    kind = (kind or "").strip()
    if kind:
        return f"[dispatcher worker · kind={kind}]\n\n{prompt}"
    return prompt


def _run_codex(prompt: str, kind: str) -> str:
    """Run `codex exec` on the user's flat-rate subscription. cost = $0.

    Per spec: `codex exec -s workspace-write --skip-git-repo-check <prompt>`
    with STDIN CLOSED (`< /dev/null`) so the headless agent can never block
    waiting for input. The final agent message comes back on stdout."""
    exe = _codex_path()
    if not exe:
        raise RuntimeError("codex CLI not found on PATH")
    full = _build_prompt(prompt, kind)
    cmd = [
        exe, "exec",
        "-s", "workspace-write",
        "--skip-git-repo-check",
        full,
    ]
    try:
        proc = subprocess.run(
            cmd,
            stdin=subprocess.DEVNULL,   # < /dev/null — stdin MUST be closed
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_CODEX_TIMEOUT_S,
            check=False,
            creationflags=_NO_WINDOW,
        )
    except subprocess.TimeoutExpired as ex:
        raise RuntimeError(f"codex CLI timed out after {_CODEX_TIMEOUT_S}s") from ex
    except Exception as ex:
        raise RuntimeError(f"codex CLI invocation failed: {ex}") from ex
    text = (proc.stdout or "").strip()
    if not text:
        err = (proc.stderr or "").strip()
        raise RuntimeError(
            "codex CLI produced no answer" + (f" — {err[:300]}" if err else "")
        )
    return text


def _openai_chat(base_url: str, api_key: str, model: str,
                 prompt: str, kind: str) -> str:
    """POST a single-turn /chat/completions request to an OpenAI-compatible
    endpoint and return the assistant text. Shared by the nvidia (free NIM) and
    LM-Studio (local) runners — both speak the OpenAI wire format. stdlib only.

    NOTE: this only ever targets FREE endpoints (NVIDIA_BASE_URL / LMSTUDIO_BASE);
    it is never pointed at api.openai.com — there is no code path that does so."""
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": _build_prompt(prompt, kind)}],
        "stream": False,
    }).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=body, headers=headers, method="POST",
    )
    with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT_S) as resp:
        payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    choices = payload.get("choices") or []
    if not choices:
        raise RuntimeError(f"empty completion from {base_url}")
    msg = (choices[0] or {}).get("message") or {}
    text = (msg.get("content") or "").strip()
    if not text:
        raise RuntimeError(f"no message content from {base_url}")
    return text


def _run_nvidia(prompt: str, kind: str) -> str:
    """Run a free NVIDIA NIM model via the OpenAI-compatible NIM endpoint. The
    NIM free tier carries no per-token charge — cost = $0. Requires a resolved
    key (the caller checks `_nvidia_key()` first)."""
    key = _nvidia_key()
    if not key:
        raise RuntimeError("no NVIDIA key resolves (free NIM tier unavailable)")
    return _openai_chat(NVIDIA_BASE_URL, key, NVIDIA_DEFAULT_MODEL, prompt, kind)


def _run_ollama(prompt: str, kind: str) -> str:
    """Run a local model via Ollama's /api/chat. Local inference — cost = $0."""
    body = json.dumps({
        "model": OLLAMA_DEFAULT_MODEL,
        "messages": [{"role": "user", "content": _build_prompt(prompt, kind)}],
        "stream": False,
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{OLLAMA_BASE.rstrip('/')}/api/chat",
        data=body, headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT_S) as resp:
        payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    # /api/chat (non-stream) → {"message": {"content": ...}}
    msg = payload.get("message") or {}
    text = (msg.get("content") or "").strip()
    if not text:
        raise RuntimeError("no message content from Ollama")
    return text


def _run_lmstudio(prompt: str, kind: str) -> str:
    """Run a local model loaded in LM Studio via its OpenAI-compatible server.
    Local inference — cost = $0. (LM Studio ignores the auth header.)"""
    return _openai_chat(LMSTUDIO_BASE, "lm-studio", "local-model", prompt, kind)


# ─────────────────────────── the fleet ─────────────────────────────────


class FreeFleet:
    """Routes dispatcher worker prompts to FREE inference only.

    `run_worker(prompt, kind)` returns `{text, provider, cost_usd: 0.0}`. The
    selected provider is always passed through `assert_free`, so a metered
    provider can never be returned — the money firewall. `available()` reports
    which free providers are reachable right now."""

    def __init__(self, probe_timeout: float = _PROBE_TIMEOUT_S) -> None:
        self._probe_timeout = float(probe_timeout)

    # ---- reachability -----------------------------------------------------

    def available(self) -> list[str]:
        """Which FREE providers are reachable RIGHT NOW, in preference order.

        - codex_cli — iff the binary is on PATH (no network probe).
        - nvidia    — iff a key resolves (free NIM tier).
        - ollama / lmstudio — iff their local endpoint answers a short probe.

        Every entry is on `FREE_PROVIDERS` by construction; a metered provider
        is never reported."""
        out: list[str] = []
        if _codex_available():
            out.append("codex_cli")
        if _nvidia_key():
            out.append("nvidia")
        if _probe_ollama(self._probe_timeout):
            out.append("ollama")
        if _probe_lmstudio(self._probe_timeout):
            out.append("lmstudio")
        # invariant: never leak a non-free provider
        return [p for p in out if p in FREE_PROVIDERS]

    # ---- the worker call --------------------------------------------------

    def run_worker(self, prompt: str, kind: str = "") -> dict:
        """Route ONE worker prompt to the first reachable FREE provider and
        return `{text, provider, cost_usd: 0.0}`.

        Preference order: codex_cli → nvidia (iff key) → ollama → lmstudio.
        Every branch routes its provider name through `assert_free` before
        returning, so the result can only ever name a free provider — cost is
        hard-coded 0.0 because every backend is flat-rate / free-tier / local.

        Raises RuntimeError when NO free provider is reachable (fail-closed —
        it never reaches for a paid provider as a fallback)."""
        errors: list[str] = []

        # (1) codex — flat-rate ChatGPT/Codex subscription.
        if _codex_available():
            try:
                text = _run_codex(prompt, kind)
                return self._result(text, "codex_cli")
            except Exception as ex:
                errors.append(f"codex_cli: {ex}")

        # (2) NVIDIA NIM free tier — only when a key resolves.
        if _nvidia_key():
            try:
                text = _run_nvidia(prompt, kind)
                return self._result(text, "nvidia")
            except Exception as ex:
                errors.append(f"nvidia: {ex}")

        # (3) local — Ollama, then LM Studio.
        if _probe_ollama(self._probe_timeout):
            try:
                text = _run_ollama(prompt, kind)
                return self._result(text, "ollama")
            except Exception as ex:
                errors.append(f"ollama: {ex}")
        if _probe_lmstudio(self._probe_timeout):
            try:
                text = _run_lmstudio(prompt, kind)
                return self._result(text, "lmstudio")
            except Exception as ex:
                errors.append(f"lmstudio: {ex}")

        raise RuntimeError(
            "FreeFleet: no FREE provider reachable (refusing to spend metered "
            "API money). Tried: codex_cli/nvidia/ollama/lmstudio. "
            + ("; ".join(errors) if errors else
               "none available — start Ollama/LM Studio, install codex, or set "
               "a free NVIDIA_API_KEY.")
        )

    @staticmethod
    def _result(text: str, provider: str) -> dict:
        """Build the worker result, passing `provider` through the firewall.
        cost_usd is ALWAYS 0.0 — every reachable backend is free/flat-rate."""
        return {
            "text": text,
            "provider": assert_free(provider),  # firewall on the way out
            "cost_usd": 0.0,
        }


__all__ = [
    "FreeFleet",
    "assert_free",
    "FREE_PROVIDERS",
    "METERED_PROVIDERS",
    "MeteredProviderError",
    "NVIDIA_BASE_URL",
]
