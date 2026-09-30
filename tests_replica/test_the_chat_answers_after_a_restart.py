"""The chat answers after a restart, because the pick survives one.

The founder said he talks to the agents in chat and nothing answers. The
model pick lived only on an in-memory attribute, so every restart left
BABOOM, the relay and the cockpit ask bar with an empty model and the
composer raised "No model chosen" -- a refusal he never saw (2026-09-07).

The pick is now the graph's composer_model (test_composer_model_is_graph_held)
and an older build's file beside the graph is still read back while the graph
holds none. With no pick and no configured default nothing is chosen for him:
the router fallback that picked a reachable provider was removed on his rule
of 2026-09-23 (test_chat_uses_only_the_configured_model, test_first_run_no_route).
"""
from __future__ import annotations

import types

import pytest

from nodelang import agent_composer
from nodelang import model_router


def _chosen(monkeypatch, *, picked):
    monkeypatch.setattr(agent_composer, "_DEFAULT_MODEL", "")
    # A provider this machine can reach must never be picked on his behalf:
    # choosing may not even ask what is reachable.
    asked = []

    def reachable_rows(**kw):
        asked.append(kw)
        raise AssertionError("the choice asked which provider is reachable")

    monkeypatch.setattr(model_router, "provider_rows", reachable_rows)
    try:
        return agent_composer.chosen_model_route(picked)
    finally:
        assert asked == [], "a model was looked for on his behalf"


def test_his_own_pick_always_wins(monkeypatch):
    assert _chosen(
        monkeypatch, picked="lmstudio/his-pick",
    ) == "lmstudio/his-pick"


def test_with_no_pick_a_reachable_provider_is_never_chosen_for_him(monkeypatch):
    """The router fallback answered instead of refusing; his rule removed it."""
    with pytest.raises(agent_composer.InvalidCell) as refusal:
        _chosen(monkeypatch, picked="")
    assert agent_composer.NO_MODEL_CHOSEN in str(refusal.value)


def test_the_composer_asks_that_one_function(monkeypatch):
    """A choice nothing calls is not the choice that ships."""
    import inspect
    body = inspect.getsource(agent_composer.run_agent_composer)
    assert "chosen_model_route(model)" in body


def _reader(state_path):
    """A process with no graph pick: only an older build's file can answer."""
    from nodelang import application_server

    fake = types.SimpleNamespace(universal_state_path=str(state_path))
    for name in ("_agent_model_path", "_read_agent_model"):
        setattr(fake, name, types.MethodType(
            getattr(application_server.ApplicationServer, name), fake
        ))
    return fake


def test_an_older_builds_pick_is_read_back_after_a_restart(tmp_path):
    """A restart must not wipe what he chose before the pick moved into the graph."""
    reader = _reader(tmp_path / "graph.sqlite3")
    assert reader._read_agent_model() == ""
    reader._agent_model_path().write_text(
        "openrouter/anthropic/claude-sonnet-4.5\n", encoding="utf-8")
    assert _reader(tmp_path / "graph.sqlite3")._read_agent_model() == (
        "openrouter/anthropic/claude-sonnet-4.5")


def test_an_unreadable_record_is_no_pick_rather_than_a_crash(tmp_path):
    reader = _reader(tmp_path / "nope" / "\0bad" / "g.sqlite3")
    assert reader._read_agent_model() == ""
