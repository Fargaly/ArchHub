"""Courts for the voice rules: refused when written, not flagged in review."""
from __future__ import annotations

import pytest

from nodelang.cell_voice import (
    OVERCLAIMS,
    assert_in_voice,
    find_emoji,
    lint,
    normalise_glyphs,
)
from nodelang.universal_cell import InvalidCell


def test_plain_honest_text_is_in_voice():
    assert assert_in_voice("The court measured 16.9 ms against a 16.7 ms bar.")


def test_emoji_are_refused_anywhere_in_the_text():
    text = "The build passed \U0001F389"
    assert find_emoji(text)
    with pytest.raises(InvalidCell):
        assert_in_voice(text)


def test_an_exclamation_mark_is_refused():
    with pytest.raises(InvalidCell):
        assert_in_voice("The build passed!")


def test_every_overclaiming_word_is_caught_with_what_to_say_instead():
    for word, instead in OVERCLAIMS.items():
        findings = lint("This is %s in practice." % word)
        rules = {f.rule for f in findings}
        assert "overclaim" in rules
        assert any(instead in f.detail for f in findings)


def test_overclaims_are_caught_regardless_of_case():
    assert any(f.rule == "overclaim" for f in lint("It is SEAMLESS."))


def test_a_word_that_merely_contains_an_overclaim_is_not_flagged():
    assert lint("The regenerated manifest is current.") == ()


def test_smart_quotes_and_long_dashes_are_normalised():
    assert normalise_glyphs("‘a’ “b” – c — d") == (
        "'a' \"b\" - c -- d")


def test_an_ellipsis_becomes_three_dots():
    assert normalise_glyphs("waiting…") == "waiting..."


def test_fancy_glyphs_are_reported_as_a_finding():
    assert any(f.rule == "glyphs" for f in lint("it ‘works’"))


def test_one_piece_of_text_can_break_several_rules_and_all_are_named():
    findings = lint("Seamless \U0001F680 results!")
    assert {f.rule for f in findings} >= {"no-emoji", "no-exclamation", "overclaim"}


def test_the_refusal_names_every_rule_it_broke():
    with pytest.raises(InvalidCell) as caught:
        assert_in_voice("Seamless results!", label="headline")
    message = str(caught.value)
    assert "headline" in message
    assert "overclaim" in message and "no-exclamation" in message
