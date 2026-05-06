"""PII redactor — sanitises strings before they leave the user's machine.

Used by:
  * `telemetry.py` before sending events to PostHog
  * `sentry_init.py` before_send hook before Sentry breadcrumbs ship
  * `agents/*` log writers when they capture chat snippets

Conservative: anything that LOOKS personal gets replaced. False positives
beat data leaks. Order matters — paths first (most specific), then
project/file names, then generic identifiers.
"""
from __future__ import annotations

import re
from pathlib import Path

# ---------------------------------------------------------------------------
# Patterns. Compile once at import.
# ---------------------------------------------------------------------------

# Windows + POSIX paths. Greedy enough to catch C:\Users\fargaly\... and
# /home/<user>/... but not URL paths.
_WIN_PATH = re.compile(r"[A-Za-z]:\\(?:[^\\\s\"'<>|*?]+\\)*[^\\\s\"'<>|*?]+")
_POSIX_PATH = re.compile(r"(?:^|\s)/(?:home|Users)/[^/\s]+(?:/[^/\s]+)*")

# Common cloud-key-shaped tokens. Don't try to be exhaustive — we want
# anything starting like a known prefix to redact even if surrounded by
# garbage. Order: longest-prefix first to avoid partial matches.
_TOKEN_PREFIXES = [
    r"sk-ant-api03-[A-Za-z0-9_\-]{20,}",        # Anthropic
    r"sk-or-v1-[A-Za-z0-9_\-]{20,}",            # OpenRouter
    r"sk-proj-[A-Za-z0-9_\-]{20,}",             # OpenAI project
    r"sk-[A-Za-z0-9_\-]{20,}",                  # OpenAI legacy
    r"AIza[A-Za-z0-9_\-]{20,}",                 # Google
    r"gho_[A-Za-z0-9_\-]{20,}",                 # GitHub OAuth
    r"ghp_[A-Za-z0-9_\-]{20,}",                 # GitHub PAT
    r"github_pat_[A-Za-z0-9_]{20,}",            # GitHub fine-grained
    r"phc_[A-Za-z0-9]{20,}",                    # PostHog project key
    r"https://[a-z0-9.-]+@[oO]?\d+\.ingest\.sentry\.io/\d+",  # Sentry DSN
]
_TOKEN_RE = re.compile("|".join(_TOKEN_PREFIXES))

# Email addresses.
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")

# IPv4 (skip obvious literals like 127.0.0.1, 0.0.0.0 — those are infra,
# not user data).
_IPV4_RE = re.compile(r"\b(?!127\.0\.0\.1|0\.0\.0\.0|localhost\b)\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b")

# Project-folder-ish names that often contain client IDs (e.g. "BA-649-A-TA-…").
# Conservative: only redact when wrapped in quotes or after "project_name=".
_PROJECT_NAME_RE = re.compile(r"(?<=['\"])([A-Z0-9]+[\-_][A-Z0-9_\-]+)(?=['\"])")


def redact(text: str | None, *, drop_paths: bool = True,
           drop_tokens: bool = True, drop_emails: bool = True,
           drop_ips: bool = True) -> str:
    """Return a redacted copy of `text`. None → ''.

    Each category can be disabled by the caller (e.g. an internal log
    writer keeps paths but drops tokens). Defaults are safe for an
    egress event going to a 3rd-party SaaS.
    """
    if not text:
        return ""
    out = str(text)
    if drop_tokens:
        out = _TOKEN_RE.sub("<REDACTED-KEY>", out)
    if drop_paths:
        out = _WIN_PATH.sub("<REDACTED-PATH>", out)
        out = _POSIX_PATH.sub(" <REDACTED-PATH>", out)
    if drop_emails:
        out = _EMAIL_RE.sub("<REDACTED-EMAIL>", out)
    if drop_ips:
        out = _IPV4_RE.sub("<REDACTED-IP>", out)
    out = _PROJECT_NAME_RE.sub("<REDACTED-PROJECT>", out)
    return out


def redact_dict(d: dict | None) -> dict:
    """Walk a dict (events, breadcrumbs, properties) and redact every string
    value in-place. Numbers / bools pass through. Nested dicts + lists are
    recursed. Keys are NOT redacted — telemetry library keys are stable
    and safe."""
    if not d:
        return {}
    out: dict = {}
    for k, v in d.items():
        out[k] = _walk(v)
    return out


def _walk(v):
    if isinstance(v, str):
        return redact(v)
    if isinstance(v, dict):
        return redact_dict(v)
    if isinstance(v, (list, tuple)):
        return [_walk(x) for x in v]
    return v


def looks_redacted(text: str) -> bool:
    """Quick check used by tests — True iff the string contains no obvious
    PII patterns. Useful for asserting an event is safe before it leaves
    the process."""
    if not text:
        return True
    return not any(
        rx.search(text)
        for rx in (_WIN_PATH, _POSIX_PATH, _TOKEN_RE, _EMAIL_RE, _IPV4_RE)
    )
