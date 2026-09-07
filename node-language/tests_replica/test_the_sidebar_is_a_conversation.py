"""The sidebar is a conversation with the app, not a log you watch.

He drew a composer under the sessions and bubbles around the exchange: what
the founder said right in an accent bubble, what the app answered left in a
bordered card. The shipped panel had only a refresh button, took the relay
as a prop and never used it, and stacked both sides as full-width blocks
(2026-09-07).
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SIDE = ROOT / "nodelang" / "studio" / "atlas-side.jsx"
CLOUD = ROOT.parent / "12.PRODUCTION" / "cloud_backend" / "cockpit_assets" / "atlas-side.jsx"


def test_the_composer_sends_through_the_relay_and_refreshes_the_list():
    text = SIDE.read_text(encoding="utf-8")
    block = text[text.index("function SessionComposer"):text.index("function AgenticPanel")]
    assert "onRelay(said, true)" in block, "it must act, not just ask"
    assert "onReloadTasks()" in block, "the answer belongs in the list at once"
    assert "e.key === 'Enter'" in block, "Enter sends, as he drew it"
    assert "disabled={busy || !draft.trim()}" in block
    assert "'Not sent: '" in block, "a refusal is said, never swallowed"


def test_the_panel_actually_mounts_the_composer_with_the_relay_it_is_given():
    text = SIDE.read_text(encoding="utf-8")
    assert "<SessionComposer onRelay={onRelay} onReloadTasks={onReloadTasks} flash={flash}/>" in text
    signature = text[text.index("function AgenticPanel({"):]
    signature = signature[:signature.index(")")]
    for prop in ("onRelay", "onReloadTasks", "flash"):
        assert prop in signature, prop


def test_the_exchange_reads_as_a_conversation():
    text = SIDE.read_text(encoding="utf-8")
    assert text.count("row-reverse") >= 2, "what the founder said is right-aligned"
    assert "maxWidth: '82%'" in text, "a bubble is capped, not full width"
    assert "background: HB.accent, color: '#fff'" in text, "his accent bubble"
    assert "CONVERSATIONS WITH YOUR AGENTS" in text, "the heading his design gives it"


def test_the_cloud_sidebar_is_the_same_file():
    if not CLOUD.is_file():
        return
    lf = lambda p: p.read_text(encoding="utf-8").replace(chr(13) + chr(10), chr(10))
    assert lf(SIDE) == lf(CLOUD), "the cockpit is one surface in two places"
