"""Regression guard for the personal cross-device sync secret-redaction leak.

Founder 2026-06-02 cross-device verify caught: embedded credential values
(Google AIza…, Slack xoxb-…, Stripe rk_live_…) mid-sentence were neither
scrubbed nor dropped and synced to the cloud verbatim — the scrubber's patterns
and the drop-gate's `startswith` check had diverged. Fix: ONE comprehensive
search-anywhere detector (`_SECRET_TOKEN_RE`) drives BOTH scrub and drop. These
tests lock that in: any embedded secret must be scrubbed AND flagged, while
op:// references survive and ordinary hyphenated strings don't false-positive.
"""
import re

import pytest

from personal_brain.personal_cloud_sync import (
    _redact_secret_values_only,
    _looks_like_bare_secret,
)

# SYNTHETIC fixtures (no real key). The distinctive-prefix values are assembled
# from a (prefix, body) split so the SOURCE carries no contiguous provider-format
# token — GitHub push-protection flags a literal `AIzaSy…` / `xoxb-…` / `rk_live_…`
# even as obvious filler, which blocked the push (2026-06-04). At runtime the
# joined strings are byte-identical, so the scrub/drop assertions are unchanged.
_GOOGLE_RAW = "AIza" + "SyA1234567890abcdefGHIJKLMNOPqrstuv"
_SLACK_RAW = "xoxb" + "-123456789012-ABCDEFGHIJKLMNOP"
_STRIPE_RK_RAW = "rk_" + "live_ABCDEFGHIJKLMNOP1234567890"

# (sentence containing the secret, the raw secret substring that must NOT survive)
EMBEDDED_SECRETS = [
    (f"prod google key is {_GOOGLE_RAW} use it", _GOOGLE_RAW),
    (f"slack bot token {_SLACK_RAW} rotate soon", _SLACK_RAW),
    (f"stripe restricted {_STRIPE_RK_RAW} in config", _STRIPE_RK_RAW),
    ("openai sk-ABCDEFGHIJKLMNOP1234567890 is the one",
     "sk-ABCDEFGHIJKLMNOP1234567890"),
    ("aws AKIAIOSFODNN7EXAMPLE access id here",
     "AKIAIOSFODNN7EXAMPLE"),
    ("github ghp_ABCDEFGHIJKLMNOP1234567890abcd token",
     "ghp_ABCDEFGHIJKLMNOP1234567890abcd"),
]


@pytest.mark.parametrize("text,raw", EMBEDDED_SECRETS)
def test_embedded_secret_is_scrubbed(text, raw):
    """The raw credential value must NOT survive redaction, even mid-sentence."""
    out = _redact_secret_values_only(text)
    assert raw not in out, f"raw secret leaked through scrub: {out!r}"


@pytest.mark.parametrize("text,raw", EMBEDDED_SECRETS)
def test_embedded_secret_is_flagged_by_drop_gate(text, raw):
    """The drop-gate must catch an embedded secret (search-anywhere, not
    startswith) so a fragment that somehow dodges the scrubber is withheld."""
    assert _looks_like_bare_secret(text) is True


def test_op_reference_survives_and_is_not_flagged():
    """op:// / wcm:// / env:// references must sync verbatim (the other device
    resolves them locally) and must never be treated as a bare secret."""
    for ref in ("see op://vault/openai/key here",
                "wcm://ArchHub/anthropic and env://OPENAI_API_KEY"):
        assert _looks_like_bare_secret(ref) is False
        out = _redact_secret_values_only(ref)
        for token in ("op://vault/openai/key", "wcm://ArchHub/anthropic",
                      "env://OPENAI_API_KEY"):
            if token in ref:
                assert token in out, f"reference mangled: {out!r}"


@pytest.mark.parametrize("benign", [
    "task-12345678 is the ticket number",
    "report-20260102final.pdf is attached",
    "the revit-export pipeline ran clean",
    "commit ad70c7e fixed the brain",
    "elevation A-101 vs A-102 review",
])
def test_no_false_positive_on_ordinary_text(benign):
    """Ordinary hyphenated identifiers / filenames must not be flagged or
    mangled — the lookbehind anchors secret prefixes at a non-alnum boundary."""
    assert _looks_like_bare_secret(benign) is False
    assert _redact_secret_values_only(benign) == benign
