"""brain_inspect reports COUNTS, not only a directory tally.

The cockpit agent's brain_inspect returned the replica DIRECTORY count and the
memory-capture total, so the founder could not ask how much the brain actually
holds. It now reports replicas / fragments / facts, split by scope, read from
the replica store on disk - and still returns not one row of content.

This tree is the deployed cloud source and is retirement-bound until the
cockpit/brain port into the canonical project.

Run: python -m pytest cloud_backend/tests/test_cockpit_brain_counts.py -q
"""
from __future__ import annotations

import json

import pytest

SENTINEL = "synthetic fixture fragment text that must never be returned"


@pytest.fixture
def replicas():
    """Two user replicas + one shared firm replica, all synthetic.

    conftest._isolate_db already repointed brain_replica.DEFAULT_REPLICAS_ROOT
    at a per-test tmp dir; this only fills that root. u_beta also gets
    tombstoned rows (valid_until set) which must NOT be counted.
    """
    import brain_replica

    def add(rep, kind, n, tombstoned=False):
        for i in range(n):
            frag = {"kind": kind, "text": "%s #%d" % (SENTINEL, i),
                    "scope": "user"}
            if tombstoned:
                frag["valid_until"] = "2020-01-01T00:00:00.000Z"
            rep.upsert_fragment(frag)

    alpha = brain_replica.BrainReplica.open(user_id="u_alpha")
    add(alpha, "fact", 3)
    add(alpha, "note", 2)
    beta = brain_replica.BrainReplica.open(user_id="u_beta")
    add(beta, "fact", 1)
    add(beta, "fact", 4, tombstoned=True)
    firm = brain_replica.BrainReplica.open_shared("firm", "f_test")
    add(firm, "fact", 2)
    return {"replicas": 3, "fragments": 8, "facts": 6}


def _inspect() -> dict:
    import cockpit_agent
    return cockpit_agent.TOOLS["brain_inspect"]["run"]({})


def test_brain_inspect_reports_counts_not_only_a_directory_tally(replicas):
    out = _inspect()
    assert out["replicas_total"] == replicas["replicas"]
    assert out["fragments_total"] == replicas["fragments"]
    assert out["facts_total"] == replicas["facts"]


def test_the_counts_are_split_by_scope(replicas):
    out = _inspect()
    assert out["by_scope"]["user"] == {"replicas": 2, "fragments": 6, "facts": 4}
    assert out["by_scope"]["firm"] == {"replicas": 1, "fragments": 2, "facts": 2}


def test_a_tombstoned_fragment_is_not_counted(replicas):
    """u_beta holds 1 live fact and 4 retracted ones. Counting a tombstone
    would tell the founder the brain holds rows it has already dropped."""
    assert _inspect()["by_scope"]["user"]["facts"] == 4


def test_a_shared_firm_replica_is_counted(replicas):
    """founder_cockpit._replica_count() walks only the top level, so a firm or
    community replica never reached the founder at all."""
    out = _inspect()
    assert out["replicas_total"] == 3
    assert out["brain_replicas"]["count"] <= out["replicas_total"]


def test_no_fragment_content_or_identity_is_ever_returned(replicas):
    out = _inspect()
    blob = json.dumps(out, default=str)
    assert SENTINEL not in blob, "fragment text reached the model"
    for identity in ("u_alpha", "u_beta", "f_test"):
        assert identity not in blob, "a replica owner id reached the model"
    assert "Redacted counts only" in out["note"]


def test_an_empty_box_reports_zero_rather_than_failing(monkeypatch, tmp_path):
    """A fresh deploy has no replicas root at all. Honest zeros, no exception."""
    import brain_replica
    monkeypatch.setattr(brain_replica, "DEFAULT_REPLICAS_ROOT",
                        tmp_path / "not-created-yet")
    out = _inspect()
    assert out["replicas_total"] == 0
    assert out["fragments_total"] == 0
    assert out["facts_total"] == 0
    assert out["by_scope"] == {}


def test_brain_inspect_is_still_a_no_argument_read_tool():
    import cockpit_agent
    spec = cockpit_agent.TOOLS["brain_inspect"]
    assert spec["kind"] == "read"
    assert spec["params"] == {"type": "object", "properties": {}}
    assert "Never fact contents" in spec["desc"]
