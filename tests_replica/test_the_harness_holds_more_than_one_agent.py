"""ArchHub is a harness: several agents work one project, not one pet.

The founder runs Codex, Claude and Gemini on the same project and asked for
them to work it together. The Agent Body catalogue held three entries --
founder, baboom, baboom-execution -- so every other runtime could answer
text as a model worker but could never hold a session or claim governed
Work (2026-09-07).

These courts hold the harness and its limits: one body PER runtime, each
separately auditable, none of them wider than BABOOM, and none of them
carrying founder authority.
"""
from __future__ import annotations

import inspect

import pytest

from nodelang import universal_application as app_module


RUNTIMES = [runtime for runtime, _label in app_module._HARNESS_AGENT_RUNTIMES]


def test_the_founder_can_run_the_agents_he_actually_runs():
    assert {"codex", "claude", "gemini"} <= set(RUNTIMES), (
        "the harness must carry the runtimes he runs: %s" % RUNTIMES
    )


@pytest.mark.parametrize("runtime", RUNTIMES)
def test_every_runtime_gets_its_own_body_policy_and_control(runtime):
    """Separately auditable: no two runtimes share a root, ever."""
    body, policy, control = app_module._harness_agent_body_roots(runtime)
    assert body == "app:agent-body:%s" % runtime
    assert policy == "app:agent-body:%s-policy" % runtime
    assert control == "app:agent-control:%s" % runtime
    assert len({body, policy, control}) == 3
    for other, _label in app_module._HARNESS_AGENT_RUNTIMES:
        if other == runtime:
            continue
        assert set(app_module._harness_agent_body_roots(other)).isdisjoint(
            {body, policy, control}
        ), "%s and %s must not share a root" % (runtime, other)


@pytest.mark.parametrize("runtime", RUNTIMES)
def test_no_runtime_borrows_baboom_s_roots(runtime):
    """One agent must never be able to act as another."""
    roots = set(app_module._harness_agent_body_roots(runtime))
    assert app_module._AGENT_BODY_BABOOM_ROOT not in roots
    assert app_module._AGENT_BODY_BABOOM_POLICY_ROOT not in roots
    assert app_module._AGENT_CONTROL_BABOOM_ROOT not in roots


@pytest.mark.parametrize("runtime", RUNTIMES)
def test_every_runtime_names_its_own_rules(runtime):
    rule = app_module._harness_agent_body_rule_id_builder(runtime)
    named = rule("claim", "work")
    assert named == "app:agent-body:%s:rule:claim:work" % runtime
    assert named != app_module._baboom_agent_body_rule_id("claim", "work")


def test_the_catalogue_lists_every_runtime_with_the_work_it_may_do():
    """A body that cannot claim and submit is a decoration, not an agent."""
    source = inspect.getsource(app_module._ensure_application_agent_body_catalog)
    assert "_HARNESS_AGENT_RUNTIMES" in source, (
        "the catalogue must carry an entry per harness runtime"
    )
    assert '("claim", "submit", "block", "resume", "release")' in source
    assert "harness_bodies" in source


def test_a_harness_body_is_built_from_the_constrained_shape():
    """Never founder authority: the same constrained body BABOOM has."""
    source = inspect.getsource(
        app_module._ensure_harness_application_agent_bodies
    )
    assert "_ensure_baboom_application_agent_body_variant" in source
    assert "_ensure_application_agent_body" not in source.replace(
        "_ensure_baboom_application_agent_body_variant", ""
    ), "a harness runtime must not be given the founder body builder"


def test_provisioning_actually_builds_them():
    """A builder nothing calls is exactly the 40% he refuses to be handed."""
    source = inspect.getsource(app_module)
    calls = source.count("_ensure_harness_application_agent_bodies(")
    assert calls >= 3, (
        "definition plus both provisioning call sites; found %d" % calls
    )
    catalog_calls = source.count("_ensure_application_agent_body_catalog(")
    assert source.count("harness_bodies,\n") >= 2 or source.count(
        "harness_bodies,\r\n"
    ) >= 2, "both catalogue calls must pass the harness bodies"
    assert catalog_calls >= 3
