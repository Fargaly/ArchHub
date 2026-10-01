"""BABOOM restarts his application only when he asks for exactly that.

The one runtime action BABOOM performs itself is handing over to a fresh
launcher that installs a staged build. The audit called this a blocker: an
utterance restarts his app mid-work. It matches on the WHOLE normalised
utterance, so a phrase caught inside a sentence cannot trigger it -- and the
route is behind the founder session as of 2026-09-07. This court holds both,
so neither can quietly loosen.
"""
from __future__ import annotations

import inspect

import pytest

from nodelang import universal_application as app_module


def _aliases() -> tuple:
    for intent, aliases in app_module._BABOOM_COMMAND_SPECS:
        if intent == "restart-to-update":
            return aliases
    raise AssertionError("restart-to-update is not in the command catalogue")


def test_the_match_is_the_whole_utterance_not_a_substring():
    body = inspect.getsource(app_module.resolve_universal_baboom_utterance)
    assert "if normalized in entry.aliases:" in body, (
        "a substring match would restart his app from a sentence that merely "
        "mentions an update"
    )
    assert "entry.aliases in normalized" not in body


@pytest.mark.parametrize("said", [
    "do not install the update yet",
    "when should I update now that the build is out",
    "tell me about update now",
    "is there an update now?",
])
def test_a_sentence_that_merely_mentions_it_does_not_restart(said):
    aliases = {alias.casefold() for alias in _aliases()}
    normalized = said.casefold().rstrip("?.!")
    assert normalized not in aliases


@pytest.mark.parametrize("said", [
    "update now", "restart to update", "install the update", "Update Now?",
])
def test_asking_for_it_exactly_still_works(said):
    aliases = {alias.casefold() for alias in _aliases()}
    assert said.casefold().rstrip("?.!") in aliases


# The route that can restart proves who asked: a behavioural court now
# (test_baboom_asks_before_restart_and_answers_its_menu.py) drives the real
# machine dispatcher with a non-founder session and a spy on the restart.
