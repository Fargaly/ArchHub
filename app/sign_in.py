"""Click-only sign-in for LLM providers.

The user should never type or paste an API key into ArchHub. The flow is:

    1. User clicks  Sign in with Anthropic / OpenAI / Google.
    2. ArchHub opens that provider's API key page in the default browser.
    3. ArchHub starts watching the clipboard.
    4. User clicks "Create new key" + "Copy" on the provider's web page.
    5. The clipboard now contains a recognisable key (sk-ant-..., sk-..., AIza...).
    6. ArchHub detects the pattern, saves the key, signals success, stops watching.

Why not OAuth?
    - Anthropic OAuth is currently scoped to the Claude Code CLI on the
      Claude Max plan. It is not yet available for 3rd-party desktop apps.
    - OpenAI does not offer OAuth for API access. The ChatGPT login does
      not grant programmatic API access.
    - Google's Generative Language API uses API keys; Vertex AI uses
      gcloud OAuth which assumes a Google Cloud project and gcloud CLI.

The clipboard approach gets the user to "signed in" in two clicks (one in
ArchHub, one on the provider's site) without typing or pasting. When the
ecosystem catches up to OAuth, this module gains real OAuth providers
behind the same Provider interface.
"""
from __future__ import annotations

import re
import webbrowser
from dataclasses import dataclass


# Provider key fingerprints. Each tuple: (regex, sample-prefix-for-display).
# Anchored at the start so a stray copy of unrelated text doesn't match.
_KEY_PATTERNS: dict[str, tuple[re.Pattern[str], str]] = {
    "anthropic": (
        re.compile(r"^sk-ant-[A-Za-z0-9_\-]{20,}$"),
        "sk-ant-…",
    ),
    "openai": (
        # OpenAI keys: sk-..., sk-proj-..., sk-svcacct-... Roughly 40+ chars.
        re.compile(r"^sk-(?:proj-|svcacct-)?[A-Za-z0-9_\-]{20,}$"),
        "sk-…",
    ),
    "google": (
        # Google AI Studio keys start with "AIza"; usually 39 chars total
        # but the suffix length varies across project types. Accept anything
        # in the realistic range so we don't reject legitimate keys.
        re.compile(r"^AIza[A-Za-z0-9_\-]{30,60}$"),
        "AIza…",
    ),
    "openrouter": (
        # OpenRouter keys begin with "sk-or-" (followed by version + body).
        re.compile(r"^sk-or-[A-Za-z0-9_\-]{20,}$"),
        "sk-or-…",
    ),
}


# Where to send the user to mint a key (clipboard-watch fallback path).
KEY_URLS: dict[str, str] = {
    "anthropic":  "https://console.anthropic.com/settings/keys",
    "openai":     "https://platform.openai.com/api-keys",
    "google":     "https://aistudio.google.com/app/apikey",
    "openrouter": "https://openrouter.ai/keys",
}


# Friendly display names per provider.
DISPLAY_NAMES: dict[str, str] = {
    "anthropic":  "Anthropic",
    "openai":     "OpenAI",
    "google":     "Google",
    "openrouter": "OpenRouter",
}


# Providers that support real OAuth (PKCE) — handled by sign_in_dialog
# differently from the clipboard-watch flow.
OAUTH_PROVIDERS: set[str] = {"openrouter"}


@dataclass
class SignInPlan:
    """A small descriptor a UI needs to launch the sign-in flow."""
    provider: str
    display_name: str
    key_url: str
    key_pattern: re.Pattern[str]
    sample_prefix: str

    @staticmethod
    def for_provider(provider: str) -> "SignInPlan":
        if provider not in _KEY_PATTERNS:
            raise ValueError(f"Unknown provider: {provider}")
        pattern, sample = _KEY_PATTERNS[provider]
        return SignInPlan(
            provider=provider,
            display_name=DISPLAY_NAMES[provider],
            key_url=KEY_URLS[provider],
            key_pattern=pattern,
            sample_prefix=sample,
        )


def open_provider_page(provider: str) -> bool:
    """Open the provider's API key page in the default browser."""
    url = KEY_URLS.get(provider)
    if not url:
        return False
    try:
        return webbrowser.open(url, new=2)
    except Exception:
        return False


def looks_like_key(provider: str, candidate: str) -> bool:
    """Return True if `candidate` matches the provider's API key shape."""
    if not candidate:
        return False
    candidate = candidate.strip()
    pattern = _KEY_PATTERNS.get(provider, (None,))[0]
    if pattern is None:
        return False
    return bool(pattern.fullmatch(candidate))


def detect_provider(candidate: str) -> str | None:
    """Identify which provider a clipboard string belongs to, if any.

    Useful for a single 'Sign in to any LLM' button — the user pastes/copies
    a key and ArchHub figures out which provider it belongs to without
    asking. Returns the provider id or None.
    """
    if not candidate:
        return None
    candidate = candidate.strip()
    for provider, (pattern, _) in _KEY_PATTERNS.items():
        if pattern.fullmatch(candidate):
            return provider
    return None
