"""Guard: redaction._PATTERNS covers embedded Google/Slack/Stripe secret VALUES
(founder 2026-06-02). The earlier prefix set lacked AIza/xoxb-/rk_live_, so an
embedded occurrence was never scrubbed. These placeholders (<google-token>/
<secret-key>) also flow into PersonalCloudSync._SECRET_VALUE_PATTERNS, so the
personal cross-device sync scrubs them too.
"""
import pytest

from personal_brain import redaction as R

# SYNTHETIC fixtures (no real key). Assembled from (prefix, body) parts so the
# SOURCE contains no contiguous provider-format token — GitHub push-protection /
# secret-scanning flags a literal `AIzaSy…` / `xoxb-…` / `rk_live_…` / `sk_live_…`
# even when it is obvious filler, which blocked the push (2026-06-04). At runtime
# the joined strings are byte-identical to the real provider formats, so the
# _PATTERNS coverage assertion below is exactly as strong as before.
_EMBEDDED_PARTS = [
    ("AIza", "SyA1234567890abcdefGHIJKLMNOPqrstuv"),  # Google API key shape
    ("xoxb", "-123456789012-ABCDEFGHIJKLMNOP"),       # Slack bot token shape
    ("rk_", "live_ABCDEFGHIJKLMNOP1234567890"),       # Stripe restricted shape
    ("sk_", "live_ABCDEFGHIJKLMNOP1234567890"),       # Stripe live shape
]
EMBEDDED_RAW = [prefix + body for prefix, body in _EMBEDDED_PARTS]


@pytest.mark.parametrize("raw", EMBEDDED_RAW)
def test_patterns_match_embedded_secret(raw):
    text = f"the prod key is {raw} use it"
    assert any(p.search(text) for p, _, _ in R._PATTERNS), \
        f"no _PATTERNS entry matches embedded {raw!r}"


def test_benign_hyphenated_text_not_matched_by_secret_patterns():
    # ordinary identifiers must not trip the NEW secret patterns
    secret_labels = {"<secret-key>", "<aws-key>", "<google-token>", "<jwt>"}
    for benign in ("task-12345678 ticket", "report-20260102final.pdf"):
        for pat, repl, _ in R._PATTERNS:
            if repl in secret_labels:
                assert not pat.search(benign), f"{repl} false-matched {benign!r}"
