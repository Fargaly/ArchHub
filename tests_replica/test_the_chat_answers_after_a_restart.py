"""The chat answers after a restart, because the pick survives one.

The founder said he talks to the agents in chat and nothing answers. The
model pick lived only on an in-memory attribute, so every restart left
BABOOM, the relay and the cockpit ask bar with an empty model and the
composer raised "No model chosen" -- a refusal he never saw (2026-09-07).

Two mechanisms, and the limit that keeps them honest: the pick is recorded
on this machine and read back, and with no pick ever made the ROUTER says
what this machine can actually reach. A machine that can reach nothing
still refuses; nothing is invented and no key is guessed.
"""
from __future__ import annotations

import types

import pytest

from nodelang import agent_composer
from nodelang import model_router


def _rows(**state):
    return [
        {"id": family, "state": value, "name": family, "source": ""}
        for family, value in state.items()
    ]


def test_the_router_prefers_a_keyed_cloud_provider():
    route = model_router.first_reachable_route(
        local_probe=lambda host, port: False,
        cloud_session=None,
        secrets_loader=lambda name: "k" if name == "openrouter" else "",
        environ={},
    )
    assert route == "openrouter/anthropic/claude-sonnet-4.5"


def test_the_router_uses_a_local_runtime_when_that_is_all_there_is(monkeypatch):
    monkeypatch.setattr(
        model_router, "provider_rows",
        lambda **kw: _rows(openrouter="no key", cloud="no key",
                           lmstudio="running", ollama="not running"),
    )
    assert model_router.first_reachable_route() == "lmstudio/local-model"


def test_the_router_refuses_rather_than_invent_a_provider(monkeypatch):
    monkeypatch.setattr(
        model_router, "provider_rows",
        lambda **kw: _rows(openrouter="no key", cloud="no key",
                           lmstudio="not running", ollama="not running"),
    )
    assert model_router.first_reachable_route() is None


def _chosen(monkeypatch, *, picked, reachable):
    monkeypatch.setattr(agent_composer, "_DEFAULT_MODEL", "")
    monkeypatch.setattr(
        agent_composer, "first_reachable_route", lambda: reachable
    )
    return agent_composer.chosen_model_route(picked)


def test_a_machine_that_reaches_nothing_still_says_no_model_chosen(monkeypatch):
    with pytest.raises(agent_composer.InvalidCell) as refusal:
        _chosen(monkeypatch, picked="", reachable=None)
    assert agent_composer.NO_MODEL_CHOSEN in str(refusal.value)


def test_his_own_pick_always_wins_over_the_router(monkeypatch):
    """The router is the fallback, never an override."""
    assert _chosen(
        monkeypatch, picked="lmstudio/his-pick",
        reachable="openrouter/should-not-be-used",
    ) == "lmstudio/his-pick"


def test_with_no_pick_the_router_answers_instead_of_silence(monkeypatch):
    assert _chosen(
        monkeypatch, picked="",
        reachable="openrouter/anthropic/claude-sonnet-4.5",
    ) == "openrouter/anthropic/claude-sonnet-4.5"


def test_the_composer_asks_that_one_function(monkeypatch):
    """A choice nothing calls is not the choice that ships."""
    import inspect
    body = inspect.getsource(agent_composer.run_agent_composer)
    assert "chosen_model_route(model)" in body


def _store():
    return types.SimpleNamespace(
        snapshot=lambda: types.SimpleNamespace(revision=1, cells={})
    )


def _registry():
    return types.SimpleNamespace()


def test_the_server_records_the_pick_and_reads_it_back(tmp_path):
    """A restart must not wipe what he chose."""
    from nodelang import application_server

    fake = types.SimpleNamespace(
        universal_state_path=str(tmp_path / "graph.sqlite3"),
        _last_agent_model="",
    )
    for name in (
        "_agent_model_path", "_write_agent_model",
        "_read_agent_model", "_remember_agent_model",
    ):
        setattr(fake, name, types.MethodType(
            getattr(application_server.ApplicationServer, name), fake
        ))

    assert fake._read_agent_model() == ""
    fake._remember_agent_model("openrouter/anthropic/claude-sonnet-4.5")
    assert fake._read_agent_model() == "openrouter/anthropic/claude-sonnet-4.5"

    # A fresh process: only the file survives.
    reborn = types.SimpleNamespace(
        universal_state_path=fake.universal_state_path, _last_agent_model="",
    )
    reborn._agent_model_path = types.MethodType(
        application_server.ApplicationServer._agent_model_path, reborn
    )
    reborn._read_agent_model = types.MethodType(
        application_server.ApplicationServer._read_agent_model, reborn
    )
    assert reborn._read_agent_model() == "openrouter/anthropic/claude-sonnet-4.5"


def test_an_unwritable_machine_forgets_rather_than_crashes(tmp_path):
    from nodelang import application_server

    fake = types.SimpleNamespace(
        universal_state_path=str(tmp_path / "nope" / "\0bad" / "g.sqlite3"),
        _last_agent_model="",
    )
    for name in ("_agent_model_path", "_write_agent_model", "_read_agent_model"):
        setattr(fake, name, types.MethodType(
            getattr(application_server.ApplicationServer, name), fake
        ))
    fake._write_agent_model("openrouter/x")
    assert fake._read_agent_model() == ""
