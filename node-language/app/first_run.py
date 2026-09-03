"""First-run detection + zero-barrier onboarding gate.

Why this exists
---------------
The most technophobic architect — the one who has heard of AI but has
never installed Ollama, never created a Claude account, never copied
an API key — needs ArchHub to "just work" on first launch. Asking
them to pick between providers, paste keys, or even understand what
"Ollama" is on their very first screen is enough friction to lose
them forever.

This module gates the first launch:

  1. Check whether ANY provider is already usable (saved API key, or
     a live Ollama listener). If yes → first-run is implicitly
     complete; nothing happens.
  2. Otherwise → mark needs_onboarding=True. The shell launches the
     onboarding dialog before the chat is reachable. Dialog runs the
     silent Ollama install + model pull. When it finishes, the
     `first_run_complete` setting is flipped and we never bother the
     user again.

The detection is intentionally lenient: a missing key for one
provider doesn't trigger onboarding as long as ANOTHER provider is
configured. We only block when the user has literally zero AI
backends.

Public API
----------
    needs_onboarding() -> bool
    mark_complete()    -> None
    reset()            -> None        # for tests / "redo onboarding"
"""
from __future__ import annotations

import socket
from typing import Optional

# Providers we look at to decide "is anything configured already?"
# This list mirrors llm_router.LLM_PROVIDERS but kept local so we
# don't import that heavyweight module just to check keys.
_KEY_PROVIDERS = ("anthropic", "openai", "google", "relay")
_OLLAMA_PORT = 11434


def _has_any_api_key() -> bool:
    try:
        from secrets_store import load_api_key
    except Exception:
        return False
    for p in _KEY_PROVIDERS:
        try:
            k = load_api_key(p)
            if k and str(k).strip():
                return True
        except Exception:
            continue
    return False


def _ollama_reachable(timeout: float = 0.3) -> bool:
    """Cheap TCP probe to localhost:11434 — Ollama's HTTP API port.
    If anything answers we treat Ollama as installed + running."""
    try:
        with socket.create_connection(("127.0.0.1", _OLLAMA_PORT),
                                       timeout=timeout):
            return True
    except OSError:
        return False


def _flag(key: str) -> bool:
    try:
        from secrets_store import load_setting
        return bool(load_setting(key))
    except Exception:
        return False


def needs_onboarding() -> bool:
    """True iff the user has NOTHING configured AND has never been
    onboarded. The combination matters — a user who completed
    onboarding then chose to uninstall Ollama should not get the
    onboarding popup again every launch."""
    if _flag("first_run_complete"):
        return False
    if _has_any_api_key():
        return False
    if _ollama_reachable():
        return False
    return True


def mark_complete() -> None:
    """Persist that onboarding ran (successfully or skipped). The
    shell calls this when the onboarding dialog accepts/rejects so
    next launch is silent."""
    try:
        from secrets_store import save_setting
        save_setting("first_run_complete", True)
    except Exception:
        pass


def reset() -> None:
    """Wipe the first-run flag so the next launch shows onboarding
    again. Used by tests and the Settings "redo onboarding" link."""
    try:
        from secrets_store import save_setting
        save_setting("first_run_complete", False)
    except Exception:
        pass
