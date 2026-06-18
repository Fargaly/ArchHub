"""Reference-docs lint — the DOCS-REFERENCE lane's RED->GREEN gate.

These docs (BACKEND_SPEC, USER_DATABASE, PERMISSIONS, CLOUD_API, BRAIN) are
founder-facing reference for the FINALIZED product. The bar is "the docs match
reality": each must point at the live backend, name the real artifacts, carry
the ROADMAP banner per the ROADMAP mandate, and follow the voice rules (no
emoji, no hype words) per voice-lint.

The court verifies the live claims by curl; this test pins the structural
invariants so a future edit cannot silently reintroduce the "not yet built"
lie, drop the live URL, or sneak emoji/hype into founder copy.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

DOCS_DIR = Path(__file__).resolve().parents[1] / "docs"

REFERENCE_DOCS = [
    "BACKEND_SPEC.md",
    "USER_DATABASE.md",
    "PERMISSIONS.md",
    "CLOUD_API.md",
    "BRAIN.md",
]

LIVE_URL = "https://archhub-cloud.fly.dev"

# Hype words banned in founder-facing copy (voice-lint). Matched as whole words,
# case-insensitive.
HYPE_WORDS = [
    "blazing", "seamless", "effortless", "world-class", "cutting-edge",
    "revolutionary", "game-changer", "game-changing", "supercharge",
    "unleash", "unlock the power", "next-generation", "best-in-class",
    "state-of-the-art", "leverage synerg", "magical", "delightful",
    "skyrocket", "turbocharge",
]

# Emoji / pictographic ranges. Technical arrow glyphs used in chains
# ("UI -> bridge", U+2192/U+2194) are NOT emoji and are allowed; this matcher
# targets the pictographic + emoticon + symbol blocks only.
EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001FAFF"   # symbols, pictographs, supplemental, emoji
    "\U00002600-\U000026FF"   # miscellaneous symbols
    "\U00002700-\U000027BF"   # dingbats
    "\U0001F1E6-\U0001F1FF"   # regional indicators
    "\U0000FE00-\U0000FE0F"   # variation selectors
    "\U00002B00-\U00002BFF"   # arrows/stars block w/ emoji stars
    "]"
)


def _read(name: str) -> str:
    return (DOCS_DIR / name).read_text(encoding="utf-8")


@pytest.mark.parametrize("name", REFERENCE_DOCS)
def test_doc_exists_and_nonempty(name: str) -> None:
    p = DOCS_DIR / name
    assert p.exists(), f"{name} is missing"
    assert len(p.read_text(encoding="utf-8").strip()) > 400, f"{name} is too thin"


@pytest.mark.parametrize("name", REFERENCE_DOCS)
def test_doc_carries_roadmap_banner(name: str) -> None:
    """ROADMAP mandate: every reference doc points back at docs/ROADMAP.md and
    flags itself as reference, not the roadmap."""
    text = _read(name).lower()
    assert "docs/roadmap.md" in text, f"{name} must reference docs/ROADMAP.md"
    assert "reference" in text and "not the roadmap" in text, (
        f"{name} must carry the 'reference - not the roadmap' banner"
    )


@pytest.mark.parametrize("name", REFERENCE_DOCS)
def test_doc_points_at_live_backend(name: str) -> None:
    assert LIVE_URL in _read(name), f"{name} must name the live backend {LIVE_URL}"


def test_backend_spec_documents_the_live_user_database() -> None:
    """The on-main BACKEND_SPEC wrongly said the backend was 'not yet built'.
    The refresh must drop that lie and document the real tables."""
    spec = _read("BACKEND_SPEC.md")
    lowered = spec.lower()
    assert "not yet built" not in lowered, "the 'not yet built' lie is back"
    # The persistent, encrypted Fly volume claim (verified live).
    assert "/data/archhub_cloud.db" in spec
    assert "volume" in lowered and "survive" in lowered
    # The real tables the founder asked to see saved + documented.
    for table in (
        "users", "tokens", "codes", "companies", "company_members",
        "company_invites", "credit_grants", "usage_log", "training_samples",
        "schema_meta",
    ):
        assert table in spec, f"BACKEND_SPEC must document the `{table}` table"


def test_user_database_is_inspectable() -> None:
    """USER_DATABASE closes the founder's 'PROPER USER DATABASE ... SAVED AND
    DOCUMENTED' ask: it names the file, the volume, and the inspect one-liner."""
    text = _read("USER_DATABASE.md")
    assert "/data/archhub_cloud.db" in text
    assert "fly ssh console" in text
    assert "sqlite3" in text
    assert "users" in text.lower()


def test_permissions_documents_role_model() -> None:
    text = _read("PERMISSIONS.md").lower()
    for role in ("owner", "admin", "member"):
        assert role in text, f"PERMISSIONS must document the `{role}` role"
    assert "invite" in text and "transfer" in text and "seat" in text


def test_cloud_api_documents_desktop_wiring() -> None:
    text = _read("CLOUD_API.md")
    assert "cloud_client.py" in text
    assert "cloud_auth.py" in text
    assert "cloud.json" in text
    assert "/v1/me" in text and "/healthz" in text


def test_brain_doc_documents_daemon() -> None:
    text = _read("BRAIN.md")
    assert "8473" in text, "BRAIN must name the daemon port 8473"
    lowered = text.lower()
    # The six workers + the surfaces.
    assert "six workers" in lowered or "6 workers" in lowered
    assert "watchdog" in lowered and "reflexion" in lowered
    assert "brainchip" in lowered and "brainviewmodal" in lowered


@pytest.mark.parametrize("name", REFERENCE_DOCS)
def test_doc_has_no_emoji(name: str) -> None:
    """Voice: no emoji in founder copy. Technical arrows (-> <->) are allowed."""
    hits = EMOJI_RE.findall(_read(name))
    assert not hits, f"{name} contains emoji: {sorted(set(hits))}"


@pytest.mark.parametrize("name", REFERENCE_DOCS)
def test_doc_has_no_hype_words(name: str) -> None:
    """Voice: plain English, no hype words."""
    text = _read(name).lower()
    found = [w for w in HYPE_WORDS if re.search(r"\b" + re.escape(w), text)]
    assert not found, f"{name} contains hype words: {found}"
