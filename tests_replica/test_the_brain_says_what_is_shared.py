"""Court: the Brain screens say what is shared, and sharing is one button on one fact.

Audit 2026-09-29: sign-up said the brain is "never uploaded to us" and "not our
servers" while the product was being wired to the Community Brain. The copy now
states the real split, and Settings > Brain offers "share" per fact, which calls
the owner-only brain-publish route.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STUDIO = ROOT / "nodelang" / "studio"


def _read(name):
    return (STUDIO / name).read_text(encoding="utf-8")


def test_the_bridge_posts_to_the_owner_only_publish_route():
    html = _read("studio.html")
    assert "window.ARCHHUB_BRAIN_PUBLISH = id =>\n      jpost('/api/universal/brain-publish', {id});" in html


def test_each_fact_offers_share_only_when_the_app_can_publish():
    jsx = _read("studio-lm.jsx")
    assert "const said = await window.ARCHHUB_BRAIN_PUBLISH(m.id);" in jsx
    assert "{window.ARCHHUB_BRAIN_PUBLISH && (" in jsx and "onClick={() => share(f)}" in jsx
    assert "reviewed before other members see it" in jsx


def test_sign_up_no_longer_says_nothing_is_ever_uploaded():
    jsx = _read("studio-account.jsx")
    for gone in ("never uploaded to us", "not our servers"):
        assert gone not in jsx, gone
    assert "Nothing is uploaded unless you share it" in jsx
    assert "Sharing is refused when a fact names the client folder or a project code." in jsx


def test_the_gate_table_names_where_the_review_happens():
    assert "a solo account is its own firm; the founder review is in the cloud" in _read("brain-model.jsx")