"""BABOOM speaks in plain sentences, never in glued counters.

The founder's screenshot (2026-09-28) read: "Work: 33 active. Workshop: 59700
entries. Attention: 0 blocked. Next review: A wire can own its parameters
claude on: Stop the brain multiplying, and write the day down baboom on: ...
Brain: 1939 facts. Hosts down: Dropbox." These courts hold the composer that
replaced that line: one to three short sentences, what needs him first, no
internal counters, no identifiers, every sentence closed.
"""
from __future__ import annotations

import itertools
import re
from pathlib import Path
from types import MappingProxyType

from nodelang.baboom_companion_placement import Rect
from nodelang.baboom_native_host import BaboomNativeSnapshot
from nodelang.baboom_native_visual import project_baboom_native_visual_frame
from nodelang.baboom_speech import compose_baboom_speech, sentences_of
from nodelang.baboom_visual_assets import BaboomSpriteAtlas

_COUNTER = re.compile(r"\b(Work|Workshop|Attention|Brain|Hosts down|Next \w+)\s*:")
_IDENTIFIER = re.compile(
    r"sha256|[0-9a-f]{7,}|[0-9a-f]{8}-[0-9a-f]{4}-|\b\w+:\w+:|\(\+\d+ more\)|\bbuild [0-9a-f]",
    re.IGNORECASE,
)


def _screenshot_briefing() -> dict:
    """The exact state behind the founder's screenshot."""
    return {
        "context": {
            "revision": 7,
            "work": {"total": 33, "open": 20, "claimed": 2, "blocked": 0, "review": 11},
            "attention": {"open_obligations": 0, "blocked_obligations": 0},
            "agents": {
                "working": [
                    {"title": "Stop the brain multiplying, and write the day down",
                     "state": "claimed", "agent": "claude"},
                    {"title": "Show readable Workshop participant labels",
                     "state": "claimed", "agent": "baboom"},
                ],
                "count": 2,
                "gone": [],
            },
            "brain": {"ok": True, "facts": 1939},
            "hosts": {"down": ["Dropbox"]},
            "canvas": {},
            "update": {},
        },
        "governed_work": {"revision": 7, "active": 33, "items": [
            {"state": "review", "title": "A wire can own its parameters"}]},
        "workshop": {"revision": 7, "count": 59700},
        "attention": {"revision": 7, "blocked_obligations": 0},
    }


_SCREENSHOT_DIRECTIVE = {
    "message": "claude is on: Stop the brain multiplying, and write the day down (+1 more)",
    "action": "show-claimed-work-plan",
}


def _assert_plain(text: str) -> None:
    sentences = sentences_of(text)
    assert 1 <= len(sentences) <= 3, text
    for sentence in sentences:
        assert sentence[-1] in ".?!", "an unclosed sentence runs on: %r" % text
        assert sentence[0].isupper() or sentence[0].isdigit(), text
        assert sentence.count(" on:") <= 1, "two agents glued in one sentence: %r" % text
        assert len(sentence) <= 110, "one sentence is a paragraph: %r" % text
    assert not _COUNTER.search(text), "a 'Label: N' counter survived: %r" % text
    assert not _IDENTIFIER.search(text), "an identifier reached the founder: %r" % text
    assert "Workshop" not in text and "facts" not in text, text
    assert "  " not in text and ".." not in text and ":." not in text, text


def test_the_screenshot_input_reads_like_a_person():
    speech = compose_baboom_speech(_screenshot_briefing(), _SCREENSHOT_DIRECTIVE, hour=9)
    assert speech == (
        "Morning. 33 jobs are running and nothing is stuck. "
        "Dropbox is offline \u2014 want me to check it?"
    )
    _assert_plain(speech)


def test_the_screenshot_frame_paints_the_sentence_not_the_counters():
    data = _screenshot_briefing()
    snapshot = BaboomNativeSnapshot(
        revision=7, presence_expires_at=1234.5, frame_issued_at=1200.0, frame_expires_at=1234.0,
        context=MappingProxyType(data["context"]),
        directive=MappingProxyType({
            "projection": "app:baboom-companion-directive:v1", "revision": 7,
            "persona_form": "runner", "motion": "working",
            "compact_message": _SCREENSHOT_DIRECTIVE["message"],
            "action": "show-claimed-work-plan", "action_label": "Show plan",
        }),
        report=MappingProxyType({
            "kind": "steward-briefing", "summary": "briefing", "revision": 7,
            "data": {"projection": "founder-local-baboom-steward-briefing", "revision": 7, **data},
        }),
        steward_signal_root=None,
    )
    atlas = BaboomSpriteAtlas(path=Path("C:/court/baboom/spritesheet.png"), width=1536,
                              height=2288, columns=8, rows=11, cell_width=192, cell_height=208)
    frame = project_baboom_native_visual_frame(snapshot, atlas, screen=Rect(0, 0, 1920, 1080))
    assert frame.report == (
        "33 jobs are running and nothing is stuck. "
        "Dropbox is offline \u2014 want me to check it?"
    )
    greeted = project_baboom_native_visual_frame(
        snapshot, atlas, screen=Rect(0, 0, 1920, 1080), greeting_hour=20)
    assert greeted.report.startswith("Evening. 33 jobs")


def test_an_agent_line_is_one_closed_sentence_reusing_the_apps_own():
    data = _screenshot_briefing()
    data["context"]["hosts"] = {"down": []}
    data["context"]["work"]["review"] = 0
    data["governed_work"]["items"] = []
    speech = compose_baboom_speech(data, _SCREENSHOT_DIRECTIVE)
    assert speech == (
        "33 jobs are running and nothing is stuck. "
        "Claude is working on: stop the brain multiplying."
    )


def test_zero_attention_and_hosts_up_says_so_briefly():
    data = _screenshot_briefing()
    data["context"].update(hosts={"down": []}, agents={"working": [], "count": 0, "gone": []})
    data["context"]["work"].update(review=0, open=0)
    data["governed_work"] = {"revision": 7, "active": 2, "items": []}
    speech = compose_baboom_speech(data, {"message": "", "action": ""})
    assert speech == "Two jobs are running and nothing is stuck."
    _assert_plain(speech)


def test_stale_claims_are_not_called_running():
    data = _screenshot_briefing()
    data["context"].update(hosts={"down": []}, agents={"working": [], "count": 0, "gone": []})
    data["context"]["work"].update(claimed=1, review=0, open=0, stale_claims=36)
    data["governed_work"] = {"revision": 7, "active": 1, "stale_claims": 36, "items": []}
    speech = compose_baboom_speech(data, {"message": "", "action": ""})
    assert speech == "One job is running and nothing is stuck. 36 old claims are held by agents that stopped."


def test_several_hosts_down_are_named_in_one_sentence():
    data = _screenshot_briefing()
    data["context"]["hosts"] = {"down": ["dropbox", "revit", "3dsmax"]}
    speech = compose_baboom_speech(data, _SCREENSHOT_DIRECTIVE)
    assert speech.endswith(
        "Dropbox, Revit and 3ds Max are offline \u2014 want me to check them?")
    _assert_plain(speech)


def test_what_needs_him_leads_and_carries_one_offer():
    data = _screenshot_briefing()
    data["context"]["brain"] = {"ok": False, "facts": 0}
    speech = compose_baboom_speech(
        data, {"message": "Your brain is not answering.", "action": "brain-health"}, hour=14)
    assert speech == (
        "Afternoon. Your brain is not answering \u2014 want me to check on it? "
        "33 jobs are running."
    )
    data = _screenshot_briefing()
    data["context"]["work"]["blocked"] = 3
    speech = compose_baboom_speech(data, {"message": "3 blocked Work items need review.",
                                          "action": "review-governed-work"})
    assert speech == (
        "Three jobs are stuck and need your eyes \u2014 want to open them? "
        "30 others are running."
    )
    assert speech.count("?") == 1


def test_a_runtime_warning_reuses_the_apps_sentence_without_its_counter():
    data = _screenshot_briefing()
    data["context"]["agents"]["gone"] = ["codex"]
    speech = compose_baboom_speech(
        data, {"message": "A codex session stopped answering. (+1 more)", "action": "status"})
    assert speech == (
        "A Codex session stopped answering \u2014 want the details? 33 jobs are running.")
    _assert_plain(speech)


def test_no_identifier_or_hash_ever_reaches_the_bubble():
    data = _screenshot_briefing()
    data["context"]["agents"]["working"] = [
        {"title": "Fix b199ed22 relay for rt-7d69e774ade3e5e6", "state": "claimed",
         "agent": "3f9a2c1d7e"}]
    data["context"]["hosts"] = {"down": []}
    data["context"]["work"]["review"] = 0
    data["context"]["update"] = {"build_id": "a99d1bcf73c26195", "tag": "v1.7"}
    data["governed_work"]["items"] = []
    for directive in (
        {"message": "Update ready (build a99d1bcf73c26195). Restart to install it.",
         "action": "restart-to-update"},
        {"message": "3f9a2c1d7e is on: Fix b199ed22 relay", "action": "show-claimed-work-plan"},
    ):
        speech = compose_baboom_speech(data, directive)
        _assert_plain(speech)
    assert "A new build is ready" in compose_baboom_speech(data, {"message": "", "action": ""})
    data["context"]["update"] = {}
    speech = compose_baboom_speech(data, {"message": "", "action": "show-claimed-work-plan"})
    assert speech.endswith("An agent is working on: fix relay.")
    _assert_plain(speech)


def test_no_combination_of_state_ever_becomes_a_run_on():
    base = _screenshot_briefing()
    agents = (
        [],
        base["context"]["agents"]["working"],
        [{"title": "", "state": "claimed", "agent": ""}],
    )
    checked = 0
    for (blocked, review, open_, holds, brain, gone, hosts, update, working, active, hour, action) in itertools.product(
        (0, 1, 4), (0, 2), (0, 1), (0, 1), (True, False, None), ((), ("codex",)),
        ((), ("dropbox",), ("revit", "rhino")), ({}, {"build_id": "abc1234def"}),
        agents, (0, 1, 33), (None, 7, 23),
        ("", "status", "show-claimed-work-plan", "review-governed-work"),
    ):
        data = {
            "context": {
                "work": {"total": active, "open": open_, "claimed": len(working),
                         "blocked": blocked, "review": review},
                "attention": {"blocked_obligations": holds},
                "agents": {"working": list(working), "count": len(working), "gone": list(gone)},
                "brain": {"ok": brain, "facts": 12},
                "hosts": {"down": list(hosts)},
                "canvas": {"failed": ["pdf.publish"]} if gone else {},
                "update": update,
            },
            "governed_work": {"active": active, "items": [{"state": "review", "title": "A wire"}]},
            "workshop": {"count": 59700},
            "attention": {"blocked_obligations": holds},
        }
        speech = compose_baboom_speech(data, {"message": "", "action": action}, hour=hour)
        _assert_plain(speech)
        checked += 1
    assert checked == 3 * 2 * 2 * 2 * 3 * 2 * 3 * 2 * 3 * 3 * 3 * 4


def test_the_counter_line_is_gone_from_every_surface():
    import inspect

    from nodelang import baboom_native_companion, baboom_native_visual
    for module in (baboom_native_visual, baboom_native_companion):
        src = inspect.getsource(module)
        for glued in ('f"Work: {', '"Workshop: {', 'f"Attention: {', "on: {row", "Brain: {", '"Hosts down: "', '" \u00b7 ".join'):
            assert glued not in src, (module.__name__, glued)
    assert not hasattr(baboom_native_visual, "baboom_actionable_report_text")


def test_a_malformed_report_is_refused_never_spoken_calmly():
    import pytest

    def broken(mutate):
        data = _screenshot_briefing()
        mutate(data)
        return data

    malformed = (
        None,
        "Work: 33 active.",
        [],
        broken(lambda d: d.pop("governed_work")),
        broken(lambda d: d.update(workshop=None)),
        broken(lambda d: d.update(attention=[])),
        broken(lambda d: d["governed_work"].update(active="33")),
        broken(lambda d: d["governed_work"].update(active=True)),
        broken(lambda d: d["workshop"].pop("count")),
        broken(lambda d: d["attention"].update(blocked_obligations=None)),
        broken(lambda d: d["governed_work"].update(items="review")),
        broken(lambda d: d["governed_work"].update(items=[{"state": "review"}, "blocked"])),
    )
    for report in malformed:
        with pytest.raises(ValueError, match="BABOOM native report is invalid"):
            compose_baboom_speech(report, _SCREENSHOT_DIRECTIVE)
    assert compose_baboom_speech(_screenshot_briefing(), _SCREENSHOT_DIRECTIVE)
