"""The three ask boxes keep the three scales he drew.

His handoff draws the canvas composer at 14px with an 11.5px Send, the chat
reply at 13.5, and the one inside a node at 12 with a 10px Send. All three
call sites were collapsed onto the smallest, so the largest ask on the
screen read as node chrome (2026-09-07).
"""
from __future__ import annotations

import re
from pathlib import Path

STUDIO = Path(__file__).resolve().parents[1] / "nodelang" / "studio" / "studio-lm.jsx"


def _table() -> str:
    text = STUDIO.read_text(encoding="utf-8")
    start = text.index("const ASK_SCALE = {")
    return text[start:text.index("};", start)]


def test_the_scale_table_carries_his_three_sizes():
    table = _table()
    assert "composer:" in table and "field: 14" in table
    assert "reply:" in table and "field: 13.5" in table
    assert "node:" in table and "field: 12" in table
    assert "size: 11.5" in table and "size: 10" in table
    assert "lead: 6" in table, "the composer's field is inset, as he drew it"


def test_every_call_site_names_its_scale():
    text = STUDIO.read_text(encoding="utf-8")
    sites = re.findall(r"<InlineAsk(.*?)/>", text, re.S)
    assert len(sites) == 3, sites
    scales = sorted(re.search(r'scale="([a-z]+)"', s).group(1) for s in sites)
    assert scales == ["composer", "node", "reply"], scales


def test_the_field_and_the_button_read_the_scale_not_a_constant():
    text = STUDIO.read_text(encoding="utf-8")
    body = text[text.index("const InlineAsk ="):text.index("const NodeBody")]
    assert "fontSize:S.field" in body and "marginLeft: S.lead" in body
    assert "padding:S.send.padding" in body and "fontSize:S.send.size" in body
    assert "borderRadius:S.send.radius" in body
    assert "fontSize:12," not in body.split("style={{ flex:1")[1][:300], "no hardcoded size survives"


def test_the_provider_swatch_names_the_vendor_and_invents_nothing():
    text = STUDIO.read_text(encoding="utf-8")
    brand = text[text.index("const BRAND = {"):text.index("};", text.index("const BRAND = {"))]
    for vendor in ("openrouter", "cloud", "ollama", "lmstudio"):
        assert vendor in brand, vendor
    assert "background:BRAND[p.id] || tone(p.state)" in text
    for invented in ("this month", "ant-", "sk-", "Reveal key"):
        assert invented not in text, "the invented provider figures must stay gone: %s" % invented


def test_the_composer_names_the_slash_and_puts_send_last():
    """He drew the slash glyph, the field, library, then Send as the rightmost
    control. The placeholder stopped explaining the glyph still drawn beside
    it, and Send rendered before library (2026-09-07)."""
    text = STUDIO.read_text(encoding="utf-8")
    row = text[text.index('<InlineAsk scale="composer"'):]
    row = row[:row.index("/>") + 2]
    assert "type / to add a node" in row, "the placeholder names the affordance"
    assert "before={" in row and "library" in row
    body = text[text.index("const InlineAsk ="):text.index("const NodeBody")]
    assert body.index("{before || null}") < body.index("<button onClick={ask}"), "library sits before Send"


def test_the_session_chips_are_the_states_that_exist():
    """An 'idle' chip could never match, and scheduled and workflow sessions had
    no chip at all."""
    text = STUDIO.read_text(encoding="utf-8")
    assert "['all'].concat(Object.keys(LM_STATE_META))" in text
    assert "['all', 'running', 'idle']" not in text


def test_the_library_offers_the_speckle_host_it_can_run():
    text = STUDIO.read_text(encoding="utf-8")
    card = [l for l in text.split(chr(10)) if "id:'h_speckle'" in l]
    assert card, "the host card the template already had"
    assert "library.push_speckle" in card[0], "and it names the engine that runs"
