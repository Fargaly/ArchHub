"""Desktop launch governance expressed as NODE-LANGUAGE data, not a side policy.

This pins the architecture concern: normal desktop app interception is an
effectful governance domain, so it must be represented in the one-table node
language as a session/group with app target nodes, frozen install effects, and
court probes. The production installer may execute the effects, but it is not
the source of truth.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nodelang import Store, validate_store, relation_sources, relation_targets  # noqa: E402
from nodelang.governance_policy import build_desktop_launch_policy  # noqa: E402


def _floor(store, nid):
    return store.nodes[nid]["body"]["floor"]


def test_desktop_launch_governance_is_a_one_table_session():
    store = Store()
    policy = build_desktop_launch_policy(
        store,
        commands=("codex", "claude", "gemini", "antigravity"),
    )

    assert validate_store(store) is True
    session = store.nodes[policy["session"]]
    assert session["kind"] == "session"
    assert session["title"] == "Desktop Launch Governance"

    app_nodes = [store.nodes[nid] for nid in policy["apps"]]
    assert [n["title"] for n in app_nodes] == [
        "Desktop app: codex",
        "Desktop app: claude",
        "Desktop app: gemini",
        "Desktop app: antigravity",
    ]

    assert store.nodes[policy["watchdog_effect"]]["meta"]["frozen"] is True
    assert _floor(store, policy["watchdog_effect"])["op"] == "effect"
    assert _floor(store, policy["watchdog_effect"])["target"] == "windows-startup-task"
    assert _floor(store, policy["shortcut_effect"])["target"] == "windows-shortcuts"

    probe_kinds = {
        _floor(store, nid)["spec"]["check"]
        for nid in policy["probes"]
    }
    assert probe_kinds == {
        "brain-health",
        "hook-coverage",
        "process-ancestry-governed",
        "normal-app-watchdog",
    }


def test_desktop_launch_governance_is_wired_into_a_score_node():
    store = Store()
    policy = build_desktop_launch_policy(store, commands=("codex",))

    assert validate_store(store) is True
    assert len(policy["probe_scores"]) == len(policy["probes"])
    assert store.nodes[policy["governance_score"]]["title"] == "Desktop governance score"

    wire_pairs = {
        (
            relation_sources(store.nodes, node)[0]["node_id"],
            relation_targets(store.nodes, node)[0]["node_id"],
        )
        for wid, node in store.nodes.items()
        if node["kind"] == "wire"
    }
    for probe, score in zip(policy["probes"], policy["probe_scores"]):
        assert (probe, score) in wire_pairs
        assert (score, policy["governance_score"]) in wire_pairs

    value = store.pull(policy["governance_score"])
    assert 0.0 <= value <= 1.0
