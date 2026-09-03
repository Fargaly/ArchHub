"""The voice rules, as a refusal rather than a review comment.

Voice lint lived in CI, which means it caught things after they were written and
never at the moment anything was built. A rule that only runs in CI is a rule the
product does not have.

These are the founder rules, in the order they matter: no emoji anywhere; say
what a thing is rather than what it might be; never promise a state that has not
been proven; and no exclamation marks, because certainty is shown with evidence.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from .universal_cell import InvalidCell

# Overclaiming words: each maps to what to say instead.
OVERCLAIMS = {
    "generate": "draft",
    "guarantee": "court",
    "instantly": "in a measured time",
    "seamless": "without a step between",
    "effortless": "without extra work",
    "revolutionary": "different in a named way",
    "magic": "a mechanism",
    "perfect": "meeting its stated bar",
}

_EXCLAMATION = re.compile(r"!")
_ELLIPSIS = re.compile(r"\.\.\.|…")
_SMART_QUOTES = {"‘": "'", "’": "'", "“": '"', "”": '"'}
_DASHES = {"–": "-", "—": "--"}


@dataclass(frozen=True, slots=True)
class VoiceFinding:
    rule: str
    detail: str


def _is_emoji(character):
    if character in "‍️":
        return True
    category = unicodedata.category(character)
    if category == "So":
        return True
    return ord(character) >= 0x1F000


def find_emoji(text):
    return tuple(sorted({c for c in text if _is_emoji(c)}))


def normalise_glyphs(text):
    """Straight quotes and plain dashes, so the same word is one word."""
    for fancy, plain in {**_SMART_QUOTES, **_DASHES}.items():
        text = text.replace(fancy, plain)
    return _ELLIPSIS.sub("...", text)


def lint(text):
    """Every rule this text breaks. Empty means it is in voice."""
    findings = []
    emoji = find_emoji(text)
    if emoji:
        findings.append(VoiceFinding("no-emoji", "".join(emoji)))
    if _EXCLAMATION.search(text):
        findings.append(
            VoiceFinding("no-exclamation", "certainty is shown with evidence"))
    lowered = text.lower()
    for word, instead in OVERCLAIMS.items():
        if re.search(r"\b%s\b" % re.escape(word), lowered):
            findings.append(
                VoiceFinding("overclaim", "%s -> %s" % (word, instead)))
    if text != normalise_glyphs(text):
        findings.append(
            VoiceFinding("glyphs", "smart quotes, long dashes or an ellipsis"))
    return tuple(findings)


def assert_in_voice(text, label="text"):
    """Refuse out-of-voice text at the moment it is written, not in review."""
    findings = lint(text)
    if findings:
        raise InvalidCell(
            "%s breaks the voice rules: %s" % (
                label, "; ".join("%s (%s)" % (f.rule, f.detail) for f in findings)
            )
        )
    return True
