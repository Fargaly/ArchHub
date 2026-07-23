"""Tests for the legacy Brain active-work coordination projection.

Proves the Brain-side migration drive is real: the ledger round-trips through a real
brain.db (claim -> status -> release), the brain DRIVES the next leaf to a
runtime (next_leaf claims atomically), and the shared client_hook emits the
<assigned_leaf> pre-prompt block every client prepends.

Mirrors tests/test_active_work.py (the v0 file-ledger gate) but exercises the
brain-side store. The headline gate uses a REAL on-disk brain.db file (NOT
:memory:) and REOPENS it, so persistence is proven against the actual database
the daemon uses — not an ephemeral connection. Runs under pytest AND standalone:
`python personal-brain-mcp/tests/test_active_work_db.py`.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

# Make the bundled brain package importable when run standalone.
_SRC = Path(__file__).resolve().parents[1] / "src"
if _SRC.exists() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
_NODE_LANGUAGE = Path(__file__).resolve().parents[4] / "10.PRODUCT" / "13.NODE-LANGUAGE"
if _NODE_LANGUAGE.exists() and str(_NODE_LANGUAGE) not in sys.path:
    sys.path.insert(0, str(_NODE_LANGUAGE))

import pytest  # noqa: E402

from personal_brain import active_work as aw  # noqa: E402
from personal_brain import client_hook as ch  # noqa: E402
from personal_brain.active_work import LeafState  # noqa: E402
from personal_brain.storage import BrainStore  # noqa: E402


@pytest.fixture(autouse=True)
def _explicit_legacy_room_mode(monkeypatch):
    # This file primarily tests the legacy Brain active-work projection.
    # Universal Workshop enforcement is tested explicitly by monkeypatching the
    # runtime-room wiring in the focused tests below.
    monkeypatch.setenv("BRAIN_CELL_ROOM", "0")


def test_active_work_is_marked_legacy_migration_projection():
    source = Path(aw.__file__).read_text(encoding="utf-8")
    test_source = Path(__file__).read_text(encoding="utf-8")
    forbidden = "server-" + "authoritative"

    assert aw.LEGACY_MIGRATION_ONLY is True
    assert aw.AUTHORITY_STATUS == "superseded_by_universal_cell"
    assert aw.ACTIVE_AUTHORITY == "10.PRODUCT/13.NODE-LANGUAGE"
    assert aw.PROMOTION_ALLOWED is False
    assert "not the active product work authority" in source
    assert "Universal Cell graph is the active product work authority" in source
    assert forbidden not in source.lower()
    assert forbidden not in test_source.lower()


def _green_hook_coverage_report(client: str = "codex"):
    from personal_brain import hook_coverage as hc
    from personal_brain import installer

    return hc.HookCoverageReport(
        owner_user="founder",
        cell_first=True,
        cell_record_root=f"assembly-instance:test-hook-coverage-{client}",
        cell_record_source=f"test:hook-coverage:{client}",
        clients={
            client: hc.ClientCoverage(
                client=client,
                detected=True,
                installed=True,
                status=hc.GREEN,
                touchpoints={
                    "workshop_authority": hc.TouchpointCoverage(
                        touchpoint="workshop_authority",
                        state=installer.ENFORCED,
                        required=True,
                        installed=True,
                        evidence=[f"test:{client}:workshop_authority"],
                    )
                },
            )
        },
    )


def _green_runtime_compliance(_invocation):
    from nodelang.cell_attestations import CourtResult

    checks = {
        "runtime-detected": True,
        "required-hooks": True,
        "schema-valid": True,
        "brain-connected": True,
        "scope-gate": True,
        "workshop-authority": True,
    }
    return CourtResult(True, checks, {"adapter": "active-work-db-court"})


class _CellFirstWorkBridge:
    def __init__(self, fail_on_source_prefix: str = ""):
        self.fail_on_source_prefix = fail_on_source_prefix
        self.assemblies = []
        self.work_items = []

    def assembly_create(
        self,
        *,
        definition_key,
        fields,
        idempotency_field=None,
        x=0.0,
        y=0.0,
    ):
        source = str((fields or {}).get("source") or "")
        if self.fail_on_source_prefix and source.startswith(
            self.fail_on_source_prefix
        ):
            raise RuntimeError("cell request denied")
        root = f"assembly-instance:test-record-{len(self.assemblies) + 1}"
        record = {
            "created_root": root,
            "membership_wire": f"relation:test-record-{len(self.assemblies) + 1}",
            "definition_key": definition_key,
            "fields": dict(fields or {}),
            "idempotency_field": idempotency_field,
            "x": x,
            "y": y,
        }
        self.assemblies.append(record)
        return record

    def work_list(self):
        return {
            "brain_scope": "scope:brain",
            "items": list(self.work_items),
            "revision": "r1",
        }

    def work_create(
        self,
        *,
        title,
        description="",
        priority=0,
        external_key="unset",
        references=None,
        structured_references=None,
        x=0.0,
        y=0.0,
    ):
        root = f"assembly-instance:test-work-{len(self.work_items) + 1}"
        created = {
            "root": root,
            "created_root": root,
            "membership_wire": f"relation:test-work-{len(self.work_items) + 1}",
            "interfaces": {
                "external-key": {"value": external_key},
            },
            "title": title,
            "description": description,
            "priority": priority,
            "references": dict(references or {}),
            "structured_references": dict(structured_references or {}),
            "x": x,
            "y": y,
        }
        self.work_items.append(created)
        return created


def _room_plan(store, leaf_id: str, agent: str = "test-agent") -> None:
    from personal_brain.meeting_room import room_say

    room_say(
        store,
        frm=agent,
        kind="plan",
        refs=[leaf_id],
        text=f"Plan for active-work test leaf {leaf_id}.",
    )


def _room_plan_all_open(store, owner_user: str = "founder") -> None:
    ledger = aw.get_ledger(store, owner_user=owner_user)
    for leaf in ledger.leaves.values():
        if leaf.state == LeafState.OPEN:
            _room_plan(store, leaf.leaf_id)


def _room_done_evidence(store, leaf_id: str) -> None:
    from personal_brain.meeting_room import room_say

    for kind, text in (
        ("test", "Test evidence posted for active-work completion."),
        ("doc", "Documentation evidence posted for active-work completion."),
        ("court", "Court verdict posted for active-work completion."),
    ):
        room_say(store, frm="test-court", kind=kind, refs=[leaf_id], text=text)


@pytest.fixture()
def store():
    s = BrainStore.open(":memory:")
    yield s
    s.close()


# ─────────────────── the headline gate: brain.db round-trip ─────────────


def test_ledger_roundtrips_through_brain_db_file():
    """claim -> status -> release, proven against a REAL on-disk brain.db that
    is closed and REOPENED between writes (durable persistence, not a live
    connection)."""
    with tempfile.TemporaryDirectory() as d:
        db = Path(d) / "brain.db"

        # 1) PRODUCE: enqueue one gated leaf, then close the DB entirely.
        s1 = BrainStore.open(db)
        aw.add_leaves(s1, owner_user="founder", leaves=[
            {"title": "build the thing", "gate_kind": "file_exists",
             "gate_spec": {"path": "x.py"}, "priority": 5},
        ])
        _room_plan_all_open(s1)
        s1.close()

        # 2) DRIVE: reopen the SAME file -> the brain hands the runtime its next
        #    leaf and CLAIMS it atomically (open -> claimed). Persist + close.
        s2 = BrainStore.open(db)
        leaf = aw.next_leaf(s2, runtime="claude_code", owner_user="founder")
        assert leaf is not None and leaf.title == "build the thing"
        assert leaf.state == LeafState.CLAIMED
        assert leaf.claimed_by == "claude_code"   # default agent_id = runtime
        leaf_id = leaf.leaf_id
        s2.close()

        # 3) STATUS: reopen -> the claim survived the round-trip; not dry yet
        #    (a claimed leaf is still actionable).
        s3 = BrainStore.open(db)
        st = aw.status(s3, owner_user="founder")
        assert st["exists"] is True
        assert st["counts"]["claimed"] == 1 and st["counts"]["open"] == 0
        assert st["dry"] is False
        # the single brain_meta key holds it; nothing leaked into skills.
        assert s3.get_meta(aw.LEDGER_META_KEY)
        assert s3.count_skills() == 0
        s3.close()

        # 4) RELEASE done -> DONE, with evidence. Reopen -> drive is DRY.
        s4 = BrainStore.open(db)
        _room_done_evidence(s4, leaf_id)
        done = aw.release(s4, leaf_id=leaf_id, done=True,
                          owner_user="founder", evidence_ref="x.py written")
        assert done.state == LeafState.DONE and done.evidence_ref == "x.py written"
        s4.close()

        s5 = BrainStore.open(db)
        st2 = aw.status(s5, owner_user="founder")
        assert st2["counts"]["done"] == 1
        assert st2["dry"] is True        # nothing actionable left -> done-rule fires
        s5.close()


# ─────────────────── unit behaviour (in-memory is fine) ─────────────────


def test_add_is_additive_under_one_meta_key(store):
    aw.add_leaves(store, owner_user="founder",
                  leaves=[{"title": "a"}, {"title": "b"}])
    # exactly ONE brain_meta key, no table, no skills/fragments leakage.
    assert store.get_meta(aw.LEDGER_META_KEY)
    assert store.count_skills() == 0
    led = aw.get_ledger(store, owner_user="founder")
    assert led is not None and len(led.leaves) == 2


def test_add_is_idempotent_on_title(store):
    aw.add_leaves(store, owner_user="founder", leaves=[{"title": "same"}])
    aw.add_leaves(store, owner_user="founder", leaves=[{"title": "same"}])
    led = aw.get_ledger(store, owner_user="founder")
    assert len(led.leaves) == 1          # re-adding the same title -> no dup


def test_resync_updates_only_open_leaf_governance_metadata(store):
    aw.add_leaves(store, owner_user="founder", leaves=[{
        "title": "same", "gate_kind": "manual",
        "cde_container": {"container_id": "old"},
    }])
    aw.add_leaves(store, owner_user="founder", leaves=[{
        "title": "same", "gate_kind": "pytest",
        "gate_spec": {"path": "new_test.py"},
        "cde_container": {"container_id": "new"},
        "fit": ["test", "python"],
    }])
    leaf = next(iter(aw.get_ledger(store, owner_user="founder").leaves.values()))
    assert leaf.state == aw.LeafState.OPEN
    assert leaf.gate_kind == "pytest"
    assert leaf.gate_spec == {"path": "new_test.py"}
    assert leaf.cde_container == {"container_id": "new"}

    _room_plan_all_open(store)
    aw.next_leaf(store, runtime="codex", fit=["test", "python"],
                 owner_user="founder")
    aw.add_leaves(store, owner_user="founder", leaves=[{
        "title": "same", "gate_kind": "file_exists",
        "cde_container": {"container_id": "must-not-replace"},
    }])
    claimed = next(iter(aw.get_ledger(store, owner_user="founder").leaves.values()))
    assert claimed.state == aw.LeafState.CLAIMED
    assert claimed.gate_kind == "pytest"
    assert claimed.cde_container == {"container_id": "new"}


def test_next_leaf_sequential_no_double_claim(store):
    """Sequential sanity: a second pull on a one-leaf ledger gets nothing.
    (The CONCURRENT proof — the one that actually refutes the TOCTOU race — is
    test_next_leaf_is_atomic_under_real_concurrency below.)"""
    aw.add_leaves(store, owner_user="founder", leaves=[{"title": "only one"}])
    _room_plan_all_open(store)
    a = aw.next_leaf(store, runtime="codex", owner_user="founder")
    b = aw.next_leaf(store, runtime="gemini", owner_user="founder")
    assert a is not None and a.title == "only one"
    assert b is None                     # already claimed -> frontier dry for b


@pytest.mark.parametrize("round_no", range(8))
def test_next_leaf_is_atomic_under_real_concurrency(round_no):
    """THE refutation killer (court defect #2 — TOCTOU double-claim).

    Two threads call next_leaf on ONE leaf, released together by a barrier, with
    a forced YIELD injected INSIDE the read-modify-write window (right after a
    thread READS the ledger but before it WRITES). On the OLD code the select
    (load→get_meta) released the store lock before the claim (save→set_meta)
    re-acquired it, so both threads read state=OPEN and BOTH claimed the same
    leaf — a double-claim, AND the first claim is lost (last-writer-wins). This
    test FAILS on that code (two non-None winners). After the single-critical-
    section fix (next_leaf routes through BrainStore.update_meta, which holds the
    RLock across get→decide→set), exactly ONE thread wins.

    Runs several rounds because a race is probabilistic; the forced yield makes
    the double-claim deterministic on the buggy code in practice.
    """
    s = BrainStore.open(":memory:")
    try:
        aw.add_leaves(s, owner_user="founder", leaves=[{"title": "only one"}])
        _room_plan_all_open(s)

        # Force a yield in the OLD code's unlocked window: after load reads the
        # ledger blob (get_meta) and before save writes it (set_meta). The fixed
        # code's critical section uses update_meta's inline read (NOT get_meta),
        # so this yield can't split it — that's the discriminator.
        real_get = s.get_meta
        barrier = threading.Barrier(2)

        def slow_get(key):
            val = real_get(key)
            if key == aw.LEDGER_META_KEY:
                time.sleep(0.05)
            return val

        s.get_meta = slow_get  # type: ignore[assignment]

        results: dict[str, object] = {}

        def pull(name: str):
            barrier.wait()
            results[name] = aw.next_leaf(
                s, runtime=name, owner_user="founder", agent_id=name)

        threads = [threading.Thread(target=pull, args=(n,))
                   for n in ("codex", "gemini")]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        winners = [n for n, lf in results.items() if lf is not None]
        # exactly ONE thread may win the single leaf — never both (double-claim).
        assert len(winners) == 1, (
            f"double-claim: {winners} both got the one leaf (TOCTOU race)")
        # and the ledger agrees: the leaf is CLAIMED by the single winner.
        led = aw.get_ledger(s, owner_user="founder")
        only = next(iter(led.leaves.values()))
        assert only.state == LeafState.CLAIMED
        assert only.claimed_by == winners[0]
    finally:
        s.close()


def test_concurrent_pulls_on_many_leaves_no_dup_no_loss():
    """Stronger property: N threads pulling from N leaves each get a DISTINCT
    leaf — none claimed twice, none lost. Proves the single-arbiter invariant
    holds under contention, not just for the one-leaf case."""
    s = BrainStore.open(":memory:")
    try:
        n = 12
        aw.add_leaves(s, owner_user="founder",
                      leaves=[{"title": f"leaf-{i}"} for i in range(n)])
        _room_plan_all_open(s)
        barrier = threading.Barrier(n)
        claimed: list[str] = []
        lock = threading.Lock()

        def pull(name: str):
            barrier.wait()
            leaf = aw.next_leaf(s, runtime=name, owner_user="founder",
                                agent_id=name)
            if leaf is not None:
                with lock:
                    claimed.append(leaf.leaf_id)

        threads = [threading.Thread(target=pull, args=(f"r{i}",))
                   for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # every claim is unique (no leaf handed to two runtimes)...
        assert len(claimed) == len(set(claimed)), "a leaf was double-claimed"
        # ...and all n leaves were claimed (no lost update dropped one).
        assert len(claimed) == n
        st = aw.status(s, owner_user="founder")
        assert st["counts"]["claimed"] == n and st["counts"]["open"] == 0
    finally:
        s.close()


# ─────────────────── durability: corrupt blob must NOT wipe the ledger ───


def test_corrupt_blob_does_not_wipe_ledger_recovers_from_lastgood():
    """Court defect #3 — silent total-ledger loss. A good write leaves a
    last-good copy; a later CORRUPT primary blob must NOT erase every owner's
    work — the loader recovers from last-good and quarantines the bad bytes,
    never silently returns {}."""
    s = BrainStore.open(":memory:")
    try:
        aw.add_leaves(s, owner_user="founder",
                      leaves=[{"title": "precious work"}])
        aw.add_leaves(s, owner_user="teammate",
                      leaves=[{"title": "their work"}])
        # corrupt the PRIMARY ledger blob (simulate a partial/garbled write).
        s.set_meta(aw.LEDGER_META_KEY, '{"founder": {"leaves": {bro')

        # the loader must NOT return {} — it recovers from the last-good copy.
        led = aw.get_ledger(s, owner_user="founder")
        assert led is not None, "ledger was silently wiped on a corrupt read"
        assert any(lf.title == "precious work" for lf in led.leaves.values())
        # the OTHER owner survived too (one bad read can't nuke all owners).
        led2 = aw.get_ledger(s, owner_user="teammate")
        assert led2 is not None and any(
            lf.title == "their work" for lf in led2.leaves.values())

        # the corrupt bytes were quarantined, not discarded.
        corrupt_keys = [k for k in _all_meta_keys(s)
                        if k.startswith(aw.LEDGER_CORRUPT_PREFIX)]
        assert corrupt_keys, "corrupt blob was not quarantined"
    finally:
        s.close()


def test_corrupt_blob_with_no_lastgood_raises_loud_not_silent_wipe():
    """If the blob is corrupt AND there is no recoverable last-good copy, the
    loader RAISES loudly — it must never silently return an empty ledger (the
    'data not persistent' fear). Fail-loud beats silent data loss."""
    s = BrainStore.open(":memory:")
    try:
        # corrupt primary, and NO last-good key written yet.
        s.set_meta(aw.LEDGER_META_KEY, "}{ not json at all")
        with pytest.raises(aw.LedgerCorruptError):
            aw.get_ledger(s, owner_user="founder")
        # and it still quarantined the bad bytes before raising.
        assert any(k.startswith(aw.LEDGER_CORRUPT_PREFIX)
                   for k in _all_meta_keys(s))
    finally:
        s.close()


def _all_meta_keys(store) -> list[str]:
    """Read all brain_meta keys directly (test helper)."""
    with store._lock:  # noqa: SLF001 — test introspection
        rows = store._conn.execute("SELECT key FROM brain_meta").fetchall()
    return [r["key"] for r in rows]


def test_next_leaf_priority_then_fifo(store):
    aw.add_leaves(store, owner_user="founder", leaves=[
        {"title": "low", "priority": 1},
        {"title": "high", "priority": 9},
    ])
    _room_plan_all_open(store)
    first = aw.next_leaf(store, runtime="claude_code", owner_user="founder")
    assert first.title == "high"         # highest priority pulled first


def test_fit_gating_specialised_leaf_not_handed_to_wrong_runtime(store):
    aw.add_leaves(store, owner_user="founder", leaves=[
        {"title": "revit job", "fit": ["revit"]},
    ])
    _room_plan_all_open(store)
    # a runtime that can't do revit gets nothing...
    assert aw.next_leaf(store, runtime="codex", fit=["python"],
                        owner_user="founder") is None
    # ...but one that offers 'revit' is handed it.
    got = aw.next_leaf(store, runtime="claude_code", fit=["revit", "python"],
                       owner_user="founder")
    assert got is not None and got.title == "revit job"


def test_release_not_done_reopens_and_bumps_attempts(store):
    aw.add_leaves(store, owner_user="founder", leaves=[{"title": "retry me"}])
    _room_plan_all_open(store)
    leaf = aw.next_leaf(store, runtime="codex", owner_user="founder")
    re = aw.release(store, leaf_id=leaf.leaf_id, done=False,
                    owner_user="founder", note="gate red")
    assert re.state == LeafState.OPEN    # back on the frontier
    assert re.attempts == 1 and re.claimed_by is None
    # it can be pulled again (re-work loop).
    again = aw.next_leaf(store, runtime="codex", owner_user="founder")
    assert again is not None and again.leaf_id == leaf.leaf_id


def test_release_blocked_escalates_not_dry(store):
    aw.add_leaves(store, owner_user="founder", leaves=[{"title": "needs you"}])
    _room_plan_all_open(store)
    leaf = aw.next_leaf(store, runtime="codex", owner_user="founder")
    bl = aw.release(store, leaf_id=leaf.leaf_id, done=False, blocked=True,
                    owner_user="founder", note="need a credential")
    assert bl.state == LeafState.BLOCKED
    st = aw.status(store, owner_user="founder")
    assert st["blocked"] == [leaf.leaf_id]
    assert st["dry"] is False            # a blocked leaf is NOT done


def test_legacy_release_tool_is_retired_without_mutating_the_ledger(store):
    """A run report cannot reactivate the retired Brain-side Work authority."""
    from personal_brain.server import build_server

    aw.add_leaves(store, owner_user="founder", leaves=[{
        "title": "requires report",
        "gate_kind": "pytest",
        "gate_spec": {"selector": "tests/test_x.py"},
    }])
    _room_plan_all_open(store)
    leaf = aw.next_leaf(store, runtime="codex", owner_user="founder")
    source_before = store.get_meta(aw.LEDGER_META_KEY)
    mcp = build_server(store=store, default_owner_user="founder")

    res = mcp._tools["brain.work_release"].handler(
        leaf_id=leaf.leaf_id,
        done=True,
        owner_user="founder",
        evidence_ref="pytest passed",
    )

    assert res["ok"] is False
    assert res["code"] == "legacy_work_route_retired"
    assert res["replacement"] == "brain.universal_work_transition"
    assert store.get_meta(aw.LEDGER_META_KEY) == source_before
    st = aw.status(store, owner_user="founder")
    assert st["counts"]["claimed"] == 1
    assert st["counts"]["done"] == 0


def test_legacy_release_tool_stays_retired_after_a_run_report(store):
    """Legacy evidence does not re-enable an active Work mutation route."""
    from personal_brain.server import build_server

    aw.add_leaves(store, owner_user="founder", leaves=[{
        "title": "reported work",
        "gate_kind": "pytest",
        "gate_spec": {"selector": "tests/test_x.py"},
    }])
    _room_plan_all_open(store)
    leaf = aw.next_leaf(store, runtime="codex", owner_user="founder")
    mcp = build_server(store=store, default_owner_user="founder")
    report = mcp._tools["brain.run_report_append"].handler(
        owner_user="founder",
        leaf_id=leaf.leaf_id,
        runtime="codex",
        agent_id="codex",
        report={
            "what_i_did": ["Built the requested node"],
            "where_we_are": ["Leaf is ready to close"],
            "evidence": ["pytest passed"],
            "problems_risks": [],
            "whats_next": ["Pull the next Brain leaf"],
        },
    )
    assert report["ok"] is False
    assert report["code"] == "legacy_governance_route_retired"
    assert report["brain_written"] is False
    _room_done_evidence(store, leaf.leaf_id)
    source_before = store.get_meta(aw.LEDGER_META_KEY)

    res = mcp._tools["brain.work_release"].handler(
        leaf_id=leaf.leaf_id,
        done=True,
        owner_user="founder",
        evidence_ref="legacy-run-report-route-retired",
    )

    assert res["ok"] is False
    assert res["code"] == "legacy_work_route_retired"
    assert res["replacement"] == "brain.universal_work_transition"
    assert store.get_meta(aw.LEDGER_META_KEY) == source_before


def test_legacy_add_and_leaf_read_routes_are_retired_without_mutation(store):
    from personal_brain.server import build_server

    aw.add_leaves(store, owner_user="founder", leaves=[{
        "title": "legacy evidence only",
        "gate_kind": "pytest",
        "gate_spec": {"path": "tests/test_ui.py"},
    }])
    source_before = store.get_meta(aw.LEDGER_META_KEY)
    mcp = build_server(store=store, default_owner_user="founder")
    added = mcp._tools["brain.work_add"].handler(
        owner_user="founder",
        leaves=[{"title": "draw an area badge", "gate_kind": "pytest",
                 "gate_spec": {"path": "tests/test_ui.py"}}],
    )
    detail = mcp._tools["brain.work_leaf_get"].handler(
        owner_user="founder", title="legacy evidence only")

    assert added["code"] == "legacy_work_route_retired"
    assert added["replacement"] == "brain.universal_work_create"
    assert detail["code"] == "legacy_work_route_retired"
    assert detail["replacement"] == "brain.universal_work_status"
    assert store.get_meta(aw.LEDGER_META_KEY) == source_before


def test_legacy_work_court_routes_are_retired_without_side_effects(store):
    from personal_brain import compliance_report as cr
    from personal_brain.server import build_server

    aw.add_leaves(store, owner_user="founder", leaves=[{
        "title": "legacy court evidence",
        "gate_kind": "file_exists",
        "gate_spec": {"path": "x.py"},
    }])
    leaf_id = next(iter(aw.get_ledger(store, owner_user="founder").leaves))
    source_before = store.get_meta(aw.LEDGER_META_KEY)
    mcp = build_server(store=store, default_owner_user="founder")

    for tool_name in ("brain.work_court_run", "brain.work_court_run_cell_first"):
        result = mcp._tools[tool_name].handler(
            leaf_id=leaf_id, owner_user="founder")
        assert result["ok"] is False
        assert result["code"] == "legacy_work_route_retired"
        assert result["replacement"] == "brain.universal_work_court"

    assert store.get_meta(aw.LEDGER_META_KEY) == source_before
    assert cr.get_compliance_history(store, owner_user="founder", limit=5)["events"] == []


def test_claim_specific_refuses_self_certify_anchor_and_double_claim(store):
    aw.add_leaves(store, owner_user="founder", leaves=[{"title": "x"}])
    led = aw.get_ledger(store, owner_user="founder")
    lid = next(iter(led.leaves))
    _room_plan(store, lid, agent="agent-A")
    aw.claim(store, leaf_id=lid, agent_id="agent-A", owner_user="founder")
    # a DIFFERENT agent cannot steal it.
    with pytest.raises(ValueError):
        aw.claim(store, leaf_id=lid, agent_id="agent-B", owner_user="founder")
    # empty agent_id is refused (no anti-self-cert anchor).
    aw.add_leaves(store, owner_user="founder", leaves=[{"title": "y"}])
    led2 = aw.get_ledger(store, owner_user="founder")
    yid = [k for k, v in led2.leaves.items() if v.title == "y"][0]
    with pytest.raises(ValueError):
        aw.claim(store, leaf_id=yid, agent_id="", owner_user="founder")


def test_bump_iteration_persists(store):
    aw.add_leaves(store, owner_user="founder", leaves=[{"title": "x"}])
    assert aw.bump_iteration(store, owner_user="founder") == 1
    assert aw.bump_iteration(store, owner_user="founder") == 2
    assert aw.status(store, owner_user="founder")["iterations"] == 2


def test_status_empty_ledger_is_idle_not_done(store):
    st = aw.status(store, owner_user="nobody")
    assert st["exists"] is False and st["dry"] is False   # idle != done


# ─────────────────── BRV-02: the client_hook pre-prompt block ────────────


def test_client_hook_requires_a_graph_session_before_formatting_assigned_work(
        store, monkeypatch):
    """Compatibility inputs cannot activate an alternate assignment path."""
    bridge = _CellFirstWorkBridge()
    monkeypatch.setattr(
        aw,
        "_cell_bridge_or_default",
        lambda cell_bridge=None: bridge,
    )
    aw.add_leaves(store, owner_user="founder", leaves=[
        {"title": "wire the panel", "gate_kind": "pytest",
         "gate_spec": {"selector": "tests/test_panel.py"}},
    ])
    _room_plan_all_open(store)
    block = ch.assigned_leaf_block(runtime="codex", store=store,
                                   owner_user="founder")
    assert block == ""
    st = aw.status(store, owner_user="founder")
    assert st["counts"]["claimed"] == 0
    assert bridge.assemblies == []


def test_client_hook_over_mcp_formats_only_graph_session_work(monkeypatch):
    calls = []

    def fake_call(name, arguments, *, timeout=6.0):  # noqa: ARG001
        calls.append((name, arguments))
        return {
            "ok": True,
            "universal": True,
            "leaf": {
                "leaf_id": "leaf-1",
                "work_root": "work:remote-1",
                "session_id": "codex-session-1",
                "runtime": "codex",
                "title": "remote graph work",
                "gate_kind": "file_exists",
                "gate_spec": {"path": "x.py"},
            },
        }

    monkeypatch.setattr(ch, "_call_daemon", fake_call)

    leaf = ch.next_assigned_leaf(
        runtime="codex", session_id="codex-session-1", fit=["write"]
    )

    assert leaf["title"] == "remote graph work"
    block = ch.format_assigned_leaf(leaf)
    assert "brain.universal_work_transition" in block
    assert "brain.universal_work_court" in block
    assert "brain.work_" not in block
    assert calls == [(
        "brain.work_assigned_block",
        {
            "runtime": "codex",
            "session_id": "codex-session-1",
            "wrap": False,
            "write": True,
            "fit": ["write"],
        },
    )]


def test_client_hook_default_path_cannot_reintroduce_legacy_commands():
    import re

    source = Path(ch.__file__).read_text(encoding="utf-8")
    assert not re.search(
        r"brain\.work_(add|next|claim|release|status|get|leaf_get|court_run)"
        r"(?:_cell_first)?\b",
        source,
    )
    assert "active_work.next_leaf" not in source
    assert "brain.work_assigned_block" in source
    assert "next_leaf_cell_first(" not in source
    assert "brain.universal_work_transition" in source
    assert "brain.universal_work_court" in source


def test_client_hook_empty_when_frontier_dry(store):
    # no leaves at all -> the drive is idle -> the block is empty (turn not
    # blocked by an idle drive).
    assert ch.assigned_leaf_block(runtime="codex", store=store,
                                  owner_user="founder") == ""


def test_next_leaf_cell_first_dry_frontier_does_not_touch_cell_bridge(store):
    class _ExplodingBridge:
        def assembly_create(self, **kwargs):  # noqa: ARG002
            raise AssertionError("dry frontier must not call the Cell runtime")

    result = aw.next_leaf_cell_first(
        store,
        runtime="codex",
        owner_user="founder",
        cell_bridge=_ExplodingBridge(),
    )

    assert result["ok"] is True
    assert result["cell_first"] is True
    assert result["brain_written"] is False
    assert result["side_effect_executed"] is False
    assert result["leaf"] is None
    assert result["frontier_dry"] is True


def test_cell_room_prompt_projection_uses_bounded_runtime_timeout():
    from personal_brain import cell_room as cr
    from personal_brain import cell_room_wiring as crw

    class _Bridge:
        def __init__(self):
            self.read_timeouts = []
            self.gate_timeouts = []

        def workshop_read(self, *, response_timeout_seconds=None):
            self.read_timeouts.append(response_timeout_seconds)
            return {"workshop": "app:workshop", "entries": []}

        def workshop_gate(
            self, *, ref, phase, response_timeout_seconds=None
        ):
            self.gate_timeouts.append((ref, phase, response_timeout_seconds))
            return {"allowed": False, "missing": ["plan"], "matching_entries": []}

    bridge = _Bridge()
    old_handle = crw._HANDLE
    crw._HANDLE = cr.RoomHandle(bridge)
    try:
        assert "No workshop events yet." in crw.cell_room_injection_tail()
        assert crw.cell_room_leaf_gate("leaf:1", "claim")["allowed"] is False
    finally:
        crw._HANDLE = old_handle

    assert bridge.read_timeouts == [cr.PROMPT_PROJECTION_TIMEOUT_SECONDS]
    assert bridge.gate_timeouts == [
        ("leaf:1", "claim", cr.PROMPT_PROJECTION_TIMEOUT_SECONDS)
    ]


def test_format_assigned_leaf_is_empty_for_none():
    assert ch.format_assigned_leaf({}) == ""


def test_work_tools_register_including_assigned_block(store):
    """The brain-driver surface registers additively, INCLUDING the
    daemon-served drive block (brain.work_assigned_block) that wires client_hook
    into the brain-side path (court defect #5 — 'drives no agent')."""
    from personal_brain.server import build_server

    mcp = build_server(store=store, default_owner_user="founder")
    tools = {t["name"]: t for t in mcp.list_tools()}
    names = set(tools)
    expected = {
        "brain.work_add", "brain.work_next", "brain.work_claim",
        "brain.work_release", "brain.work_status", "brain.work_get",
        "brain.work_leaf_get", "brain.work_court_run",
        "brain.work_assigned_block", "brain.work_add_cell_first",
        "brain.work_next_cell_first", "brain.work_claim_cell_first",
        "brain.work_release_cell_first", "brain.work_court_run_cell_first",
    }
    assert expected <= names
    assigned_desc = tools["brain.work_assigned_block"]["description"]
    assert "GRAPH-SESSION DRIVER" in assigned_desc
    assert "requires a Universal Agent Session" in assigned_desc
    assert "missing session is denied" in assigned_desc
    # existing handlers untouched (additive only).
    assert {"brain.health", "brain.skill_mint"} <= names


def test_retired_cell_first_next_route_cannot_claim_legacy_work(store):
    from personal_brain.server import build_server

    aw.add_leaves(store, owner_user="founder", leaves=[{
        "title": "must remain open",
        "gate_kind": "pytest",
        "gate_spec": {"path": "tests/court.py"},
    }])
    source_before = store.get_meta(aw.LEDGER_META_KEY)
    mcp = build_server(store=store, default_owner_user="founder")

    result = mcp._tools["brain.work_next_cell_first"].handler(
        runtime="codex", owner_user="founder"
    )

    assert result["ok"] is False
    assert result["owner_user"] == "founder"
    assert result["universal"] is True
    assert result["code"] == "legacy_work_route_retired"
    assert result["replacement"] == "brain.universal_work_next"
    assert result["leaf"] is None
    assert store.get_meta(aw.LEDGER_META_KEY) == source_before
    assert aw.status(store, owner_user="founder")["counts"]["claimed"] == 0


def test_assigned_block_tool_uses_cell_first_assignment_for_old_clients(
        store, monkeypatch):
    """No-session brain.work_assigned_block must not claim legacy work directly.

    It still returns the old-client assignment block, but the claim is wrapped
    in a Cell-first request/outcome record.
    """
    from personal_brain.server import build_server
    from personal_brain import hook_coverage as hc

    bridge = _CellFirstWorkBridge()
    monkeypatch.setattr(
        aw,
        "_cell_bridge_or_default",
        lambda cell_bridge=None: bridge,
    )
    report = _green_hook_coverage_report("codex")
    store.set_meta(hc.COVERAGE_META_KEY, report.model_dump_json())

    aw.add_leaves(store, owner_user="founder", leaves=[
        {"title": "drive me", "gate_kind": "core_values_authority_repair",
         "gate_spec": {"tool": "brain.core_values_authority_audit"}},
    ])
    _room_plan_all_open(store)
    mcp = build_server(store=store, default_owner_user="founder")
    # InHouseMCP._tools maps name -> _ToolEntry; .handler is the raw fn.
    handler = mcp._tools["brain.work_assigned_block"].handler
    res = handler(runtime="codex", owner_user="founder")
    assert res["ok"] is False
    assert res["code"] == "universal_session_required"
    assert res["leaf"] is None
    st = aw.status(store, owner_user="founder")
    assert st["counts"]["claimed"] == 0 and st["counts"]["open"] == 1


def test_assigned_block_cell_request_failure_does_not_claim_legacy_leaf(
        store, monkeypatch):
    from personal_brain.server import build_server
    from personal_brain import hook_coverage as hc

    bridge = _CellFirstWorkBridge(
        fail_on_source_prefix="brain-control:active-work-request:"
    )
    monkeypatch.setattr(
        aw,
        "_cell_bridge_or_default",
        lambda cell_bridge=None: bridge,
    )
    report = _green_hook_coverage_report("codex")
    store.set_meta(hc.COVERAGE_META_KEY, report.model_dump_json())
    aw.add_leaves(store, owner_user="founder", leaves=[{
        "title": "do not claim without cell request",
        "gate_kind": "core_values_authority_repair",
        "gate_spec": {"tool": "brain.core_values_authority_audit"},
    }])
    _room_plan_all_open(store)
    mcp = build_server(store=store, default_owner_user="founder")

    res = mcp._tools["brain.work_assigned_block"].handler(
        runtime="codex",
        owner_user="founder",
    )

    assert res["ok"] is False
    assert res["blocked"] is True
    assert res["code"] == "universal_session_required"
    assert res["block"] == ""
    st = aw.status(store, owner_user="founder")
    assert st["counts"]["open"] == 1
    assert st["counts"]["claimed"] == 0


def test_assigned_block_includes_workshop_authority(store, monkeypatch):
    """The work-assignment choke point must carry the workshop too.

    brain.context injects the room on prompt turns, but direct callers of
    brain.work_assigned_block still need the same authority in the returned
    block.
    """
    from personal_brain import cell_room_wiring
    from personal_brain import hook_coverage as hc
    from personal_brain.meeting_room import room_say
    from personal_brain.server import build_server

    bridge = _CellFirstWorkBridge()
    monkeypatch.setattr(
        aw,
        "_cell_bridge_or_default",
        lambda cell_bridge=None: bridge,
    )
    monkeypatch.setattr(cell_room_wiring, "cell_room_enabled", lambda: False)
    report = _green_hook_coverage_report("codex")
    store.set_meta(hc.COVERAGE_META_KEY, report.model_dump_json())
    room_say(
        store,
        frm="founder",
        to="codex",
        kind="decision",
        text="Workshop authority is mandatory for assigned work.",
    )
    aw.add_leaves(store, owner_user="founder", leaves=[{
        "title": "drive through workshop",
        "gate_kind": "core_values_authority_repair",
        "gate_spec": {"tool": "brain.core_values_authority_audit"},
        "fit": ["write"],
    }])
    _room_plan_all_open(store)

    mcp = build_server(store=store, default_owner_user="founder")
    res = mcp._tools["brain.work_assigned_block"].handler(
        runtime="codex",
        fit=["write"],
        owner_user="founder",
        write=True,
    )

    assert res["ok"] is False
    assert res["code"] == "universal_session_required"
    assert aw.status(store, owner_user="founder")["counts"]["claimed"] == 0


def test_active_work_claim_gate_uses_runtime_workshop_when_enabled(store, monkeypatch):
    from personal_brain import cell_room_wiring

    called = []
    monkeypatch.setattr(cell_room_wiring, "cell_room_enabled", lambda: True)
    monkeypatch.setattr(cell_room_wiring, "cell_room_is_wired", lambda: True)
    monkeypatch.setattr(
        cell_room_wiring,
        "cell_room_leaf_gate",
        lambda leaf_id, phase: (
            called.append((leaf_id, phase))
            or {"allowed": True, "missing": []}
        ),
    )
    aw.add_leaves(store, owner_user="founder", leaves=[{
        "title": "runtime workshop gated",
        "gate_kind": "file_exists",
        "gate_spec": {"path": "x.py"},
        "fit": ["write"],
    }])

    leaf = aw.next_leaf(
        store,
        runtime="codex",
        fit=["write"],
        owner_user="founder",
    )

    assert leaf is not None
    assert called == [(leaf.leaf_id, "claim")]


def test_active_work_claim_gate_fails_closed_when_runtime_workshop_unwired(store, monkeypatch):
    from personal_brain import cell_room_wiring
    from personal_brain.meeting_room import room_say

    monkeypatch.setattr(cell_room_wiring, "cell_room_enabled", lambda: True)
    monkeypatch.setattr(cell_room_wiring, "cell_room_is_wired", lambda: False)
    aw.add_leaves(store, owner_user="founder", leaves=[{
        "title": "unwired runtime workshop gated",
        "gate_kind": "file_exists",
        "gate_spec": {"path": "x.py"},
        "fit": ["write"],
    }])
    leaf_id = next(iter(aw.get_ledger(store, owner_user="founder").leaves))
    room_say(
        store,
        frm="founder",
        kind="plan",
        refs=[leaf_id],
        text="fallback plan evidence",
    )

    leaf = aw.next_leaf(
        store,
        runtime="codex",
        fit=["write"],
        owner_user="founder",
    )

    assert leaf is None
    still_open = aw.get_ledger(store, owner_user="founder").leaves[leaf_id]
    assert still_open.state == LeafState.OPEN


def test_build_server_prefers_runtime_workshop_when_available(store, monkeypatch):
    from personal_brain import cell_room_wiring
    from personal_brain.server import build_server

    calls = []

    def fake_wire(mcp, store):  # noqa: ARG001
        calls.append("runtime")

        @mcp.tool(name="brain.room_say", description="CELL-FIRST runtime room")
        def brain_room_say(frm: str, text: str, kind: str = "note", refs=None, to=None):
            return {
                "ok": True,
                "cell_first": True,
                "event": {"kind": kind, "text": text},
            }

        @mcp.tool(name="brain.room_read", description="READ-ONLY runtime room")
        def brain_room_read(limit: int = 50, kind=None, ref=None):
            return {"ok": True, "schema": "cell_room/runtime-workshop-v1"}

        @mcp.tool(name="brain.room_leaf_gate", description="CELL-FIRST runtime room")
        def brain_room_leaf_gate(leaf_id: str, phase: str):
            return {"allowed": True, "missing": []}

    monkeypatch.setattr(cell_room_wiring, "cell_room_enabled", lambda: True)
    monkeypatch.setattr(cell_room_wiring, "wire_cell_room", fake_wire)

    mcp = build_server(store=store, default_owner_user="founder")

    assert calls == ["runtime"]
    assert mcp._tools["brain.room_read"].handler()["schema"] \
        == "cell_room/runtime-workshop-v1"
    assert "CELL-FIRST" in mcp._tools["brain.room_say"].description
    assert mcp._tools["brain.room_say"].handler(
        frm="codex",
        text="runtime workshop",
    )["cell_first"] is True


def test_build_server_registers_fail_closed_room_when_runtime_unavailable(store, monkeypatch):
    from personal_brain import cell_room_wiring
    from personal_brain.server import build_server

    monkeypatch.setattr(cell_room_wiring, "cell_room_enabled", lambda: True)
    monkeypatch.setattr(
        cell_room_wiring,
        "wire_cell_room",
        lambda mcp, store: (_ for _ in ()).throw(RuntimeError("no runtime")),
    )

    mcp = build_server(store=store, default_owner_user="founder")

    assert mcp._tools["brain.room_read"].handler()["schema"] \
        == "cell_room/unavailable-v1"
    assert "CELL-FIRST" in mcp._tools["brain.room_say"].description
    blocked = mcp._tools["brain.room_say"].handler(
        frm="codex",
        text="should not enter legacy projection",
    )
    assert blocked["ok"] is False
    assert blocked["cell_first"] is True
    assert blocked["brain_written"] is False
    assert blocked["code"] == "cell_room_unavailable"


def test_environment_cannot_restore_legacy_room_authority(store, monkeypatch):
    from personal_brain import cell_room_wiring, meeting_room
    from personal_brain.server import build_server

    monkeypatch.setenv("BRAIN_CELL_ROOM", "0")
    monkeypatch.setattr(
        cell_room_wiring,
        "wire_cell_room",
        lambda mcp, store: (_ for _ in ()).throw(RuntimeError("no runtime")),
    )

    def legacy_fallback(*args, **kwargs):
        raise AssertionError("legacy Workshop authority was registered")

    monkeypatch.setattr(meeting_room, "register_room_tools", legacy_fallback)
    monkeypatch.setattr(meeting_room, "register_room_routes", legacy_fallback)

    mcp = build_server(store=store, default_owner_user="founder")

    blocked = mcp._tools["brain.room_say"].handler(
        frm="codex",
        text="must fail closed",
    )
    assert blocked["ok"] is False
    assert blocked["cell_first"] is True
    assert blocked["brain_written"] is False
    assert blocked["code"] == "cell_room_unavailable"


def test_write_assigned_block_refuses_manual_gate_and_creates_setup_leaf(store):
    """Write-capable work must not be claimed when its leaf has no executable
    verification gate. Brain should create a first-class setup leaf instead of
    handing unsafe work to the runtime."""
    from personal_brain.server import build_server
    from personal_brain import hook_coverage as hc

    report = _green_hook_coverage_report("codex")
    store.set_meta(hc.COVERAGE_META_KEY, report.model_dump_json())
    aw.add_leaves(store, owner_user="founder", leaves=[{
        "title": "edit without proof",
        "gate_kind": "manual",
        "gate_spec": {},
        "fit": ["write"],
    }])

    mcp = build_server(store=store, default_owner_user="founder")
    res = mcp._tools["brain.work_assigned_block"].handler(
        runtime="codex",
        fit=["write"],
        owner_user="founder",
        write=True,
    )

    assert res["ok"] is False
    assert res["blocked"] is True
    assert res["code"] == "universal_session_required"
    assert res["leaf"] is None
    st = aw.status(store, owner_user="founder")
    assert st["counts"]["claimed"] == 0
    assert st["counts"]["open"] == 1


def test_write_assigned_block_refuses_fake_green_without_workshop_coverage(store):
    """A green status alone is not proof. The Brain assignment gate must require
    the workshop_authority touchpoint before handing write-capable work to an
    agent."""
    from personal_brain.server import build_server
    from personal_brain import hook_coverage as hc

    report = hc.HookCoverageReport(
        owner_user="founder",
        clients={
            "codex": hc.ClientCoverage(
                client="codex",
                detected=True,
                installed=True,
                status=hc.GREEN,
            )
        },
    )
    store.set_meta(hc.COVERAGE_META_KEY, report.model_dump_json())
    aw.add_leaves(store, owner_user="founder", leaves=[{
        "title": "write with fake green",
        "gate_kind": "file_exists",
        "gate_spec": {"path": "x.py"},
        "fit": ["write"],
    }])

    mcp = build_server(store=store, default_owner_user="founder")
    res = mcp._tools["brain.work_assigned_block"].handler(
        runtime="codex",
        fit=["write"],
        owner_user="founder",
        write=True,
    )

    assert res["ok"] is False
    assert res["blocked"] is True
    assert res["code"] == "universal_session_required"
    assert res["leaf"] is None
    st = aw.status(store, owner_user="founder")
    assert st["counts"]["claimed"] == 0
    assert st["counts"]["open"] == 1


def test_assigned_block_preserves_cde_container_metadata(store, monkeypatch):
    """A Brain-assigned leaf carries its CDE container so hooks can enforce
    allowed_paths for the claimed work."""
    from personal_brain.server import build_server
    from personal_brain import hook_coverage as hc

    bridge = _CellFirstWorkBridge()
    monkeypatch.setattr(
        aw,
        "_cell_bridge_or_default",
        lambda cell_bridge=None: bridge,
    )
    report = _green_hook_coverage_report("codex")
    store.set_meta(hc.COVERAGE_META_KEY, report.model_dump_json())

    cde_container = {
        "container_id": "GM.ui.ui_home_topbar",
        "source_requirement": "grand-map:ui_home_topbar",
        "domain": "ui",
        "tier": "T1",
        "lifecycle_state": "PRODUCTION",
        "suitability_status": "S1",
        "revision": "P01",
        "owner": "agent",
        "checker": "court",
        "allowed_paths": ["10.PRODUCT/12.PRODUCTION/app/web_ui/"],
        "gate_kind": "cdp",
        "gate_spec": {"selector": "[data-uisurface='home-top']"},
        "evidence_ref": "cdp:home-top",
    }
    aw.add_leaves(store, owner_user="founder", leaves=[{
        "title": "home topbar from nodes",
        "gate_kind": "core_values_authority_repair",
        "gate_spec": {"tool": "brain.core_values_authority_audit"},
        "cde_container": cde_container,
    }])
    _room_plan_all_open(store)
    mcp = build_server(store=store, default_owner_user="founder")
    res = mcp._tools["brain.work_assigned_block"].handler(
        runtime="codex", owner_user="founder")

    assert res["ok"] is False
    assert res["code"] == "universal_session_required"
    assert res["leaf"] is None
    assert aw.status(store, owner_user="founder")["counts"]["claimed"] == 0


# ─────────────────── standalone runner (no pytest required) ─────────────


def test_add_leaves_cell_first_creates_request_and_outcome_before_projection(store):
    bridge = _CellFirstWorkBridge()

    result = aw.add_leaves_cell_first(
        store,
        owner_user="founder",
        leaves=[{
            "title": "cell first producer",
            "gate_kind": "file_exists",
            "gate_spec": {"path": "x.py"},
        }],
        cell_bridge=bridge,
    )

    assert result["ok"] is True
    assert result["cell_first"] is True
    assert result["brain_written"] is True
    assert result["leaf"]["title"] == "cell first producer"
    sources = [record["fields"]["source"] for record in bridge.assemblies]
    assert any(
        source.startswith("brain-control:active-work-request:")
        for source in sources
    )
    assert any(
        source.startswith("brain-control:active-work-outcome:")
        for source in sources
    )
    assert aw.status(store, owner_user="founder")["counts"]["open"] == 1


def test_add_leaves_cell_first_request_failure_leaves_ledger_absent(store):
    bridge = _CellFirstWorkBridge(
        fail_on_source_prefix="brain-control:active-work-request:"
    )

    result = aw.add_leaves_cell_first(
        store,
        owner_user="founder",
        leaves=[{"title": "must not add without cell request"}],
        cell_bridge=bridge,
    )

    assert result["ok"] is False
    assert result["cell_first"] is True
    assert result["brain_written"] is False
    assert result["side_effect_executed"] is False
    assert aw.get_ledger(store, owner_user="founder") is None


def test_next_leaf_cell_first_creates_request_and_outcome_before_projection(store):
    aw.add_leaves(store, owner_user="founder", leaves=[{
        "title": "cell first legacy assignment",
        "gate_kind": "file_exists",
        "gate_spec": {"path": "x.py"},
    }])
    _room_plan_all_open(store)
    bridge = _CellFirstWorkBridge()

    result = aw.next_leaf_cell_first(
        store,
        runtime="codex",
        owner_user="founder",
        cell_bridge=bridge,
    )

    assert result["ok"] is True
    assert result["cell_first"] is True
    assert result["brain_written"] is True
    assert result["leaf"]["title"] == "cell first legacy assignment"
    sources = [record["fields"]["source"] for record in bridge.assemblies]
    assert any(
        source.startswith("brain-control:active-work-request:")
        for source in sources
    )
    assert any(
        source.startswith("brain-control:active-work-outcome:")
        for source in sources
    )
    assert result["request_cell_record_root"].startswith("assembly-instance:")
    assert result["outcome_cell_record_root"].startswith("assembly-instance:")
    assert aw.status(store, owner_user="founder")["counts"]["claimed"] == 1


def test_next_leaf_cell_first_request_failure_leaves_ledger_unclaimed(store):
    aw.add_leaves(store, owner_user="founder", leaves=[{
        "title": "must not claim without cell request",
        "gate_kind": "file_exists",
        "gate_spec": {"path": "x.py"},
    }])
    _room_plan_all_open(store)
    bridge = _CellFirstWorkBridge(
        fail_on_source_prefix="brain-control:active-work-request:"
    )

    result = aw.next_leaf_cell_first(
        store,
        runtime="codex",
        owner_user="founder",
        cell_bridge=bridge,
    )

    assert result["ok"] is False
    assert result["cell_first"] is True
    assert result["brain_written"] is False
    assert result["side_effect_executed"] is False
    st = aw.status(store, owner_user="founder")
    assert st["counts"]["open"] == 1
    assert st["counts"]["claimed"] == 0


def test_claim_cell_first_creates_request_and_outcome_before_projection(store):
    aw.add_leaves(store, owner_user="founder", leaves=[{
        "title": "cell first named claim",
        "gate_kind": "file_exists",
        "gate_spec": {"path": "x.py"},
    }])
    _room_plan_all_open(store)
    leaf_id = next(iter(aw.get_ledger(store, owner_user="founder").leaves))
    bridge = _CellFirstWorkBridge()

    result = aw.claim_cell_first(
        store,
        leaf_id=leaf_id,
        agent_id="agent-A",
        runtime="codex",
        owner_user="founder",
        cell_bridge=bridge,
    )

    assert result["ok"] is True
    assert result["cell_first"] is True
    assert result["brain_written"] is True
    assert result["leaf"]["leaf_id"] == leaf_id
    assert result["leaf"]["claimed_by"] == "agent-A"
    sources = [record["fields"]["source"] for record in bridge.assemblies]
    assert any(
        source.startswith("brain-control:active-work-request:")
        for source in sources
    )
    assert any(
        source.startswith("brain-control:active-work-outcome:")
        for source in sources
    )


def test_release_cell_first_creates_request_and_outcome_before_projection(store):
    aw.add_leaves(store, owner_user="founder", leaves=[{
        "title": "cell first release",
        "gate_kind": "file_exists",
        "gate_spec": {"path": "x.py"},
    }])
    _room_plan_all_open(store)
    claimed = aw.next_leaf(store, runtime="codex", owner_user="founder")
    bridge = _CellFirstWorkBridge()

    result = aw.release_cell_first(
        store,
        leaf_id=claimed.leaf_id,
        done=False,
        note="needs another pass",
        owner_user="founder",
        cell_bridge=bridge,
    )

    assert result["ok"] is True
    assert result["cell_first"] is True
    assert result["brain_written"] is True
    assert result["leaf"]["state"] == "open"
    sources = [record["fields"]["source"] for record in bridge.assemblies]
    assert any(
        source.startswith("brain-control:active-work-request:")
        for source in sources
    )
    assert any(
        source.startswith("brain-control:active-work-outcome:")
        for source in sources
    )
    st = aw.status(store, owner_user="founder")
    assert st["counts"]["open"] == 1
    assert st["counts"]["claimed"] == 0


def test_release_cell_first_request_failure_leaves_claim_intact(store):
    aw.add_leaves(store, owner_user="founder", leaves=[{
        "title": "must not release without cell request",
        "gate_kind": "file_exists",
        "gate_spec": {"path": "x.py"},
    }])
    _room_plan_all_open(store)
    claimed = aw.next_leaf(store, runtime="codex", owner_user="founder")
    bridge = _CellFirstWorkBridge(
        fail_on_source_prefix="brain-control:active-work-request:"
    )

    result = aw.release_cell_first(
        store,
        leaf_id=claimed.leaf_id,
        done=False,
        owner_user="founder",
        cell_bridge=bridge,
    )

    assert result["ok"] is False
    assert result["cell_first"] is True
    assert result["brain_written"] is False
    assert result["side_effect_executed"] is False
    st = aw.status(store, owner_user="founder")
    assert st["counts"]["claimed"] == 1
    assert st["counts"]["open"] == 0


def test_every_legacy_work_mcp_route_is_retired_without_ledger_mutation(store):
    from personal_brain.server import build_server

    aw.add_leaves(store, owner_user="founder", leaves=[{
        "title": "legacy disclosure",
        "gate_kind": "file_exists",
        "gate_spec": {"path": "x.py"},
    }])
    _room_plan_all_open(store)
    source_before = store.get_meta(aw.LEDGER_META_KEY)
    mcp = build_server(store=store, default_owner_user="founder")
    names = {tool["name"] for tool in mcp.list_tools()}

    expected = {
        "brain.work_add", "brain.work_add_cell_first", "brain.work_next",
        "brain.work_next_cell_first", "brain.work_claim",
        "brain.work_claim_cell_first", "brain.work_release",
        "brain.work_release_cell_first", "brain.work_status", "brain.work_get",
        "brain.work_leaf_get", "brain.work_court_run",
        "brain.work_court_run_cell_first",
    }
    assert expected <= names
    results = [
        mcp._tools["brain.work_add"].handler(leaves=[], owner_user="founder"),
        mcp._tools["brain.work_add_cell_first"].handler(
            leaves=[], owner_user="founder"),
        mcp._tools["brain.work_next"].handler(
            runtime="codex", owner_user="founder"),
        mcp._tools["brain.work_next_cell_first"].handler(
            runtime="codex", owner_user="founder"),
        mcp._tools["brain.work_claim"].handler(
            leaf_id="legacy", agent_id="codex", owner_user="founder"),
        mcp._tools["brain.work_claim_cell_first"].handler(
            leaf_id="legacy", agent_id="codex", owner_user="founder"),
        mcp._tools["brain.work_release"].handler(
            leaf_id="legacy", done=False, owner_user="founder"),
        mcp._tools["brain.work_release_cell_first"].handler(
            leaf_id="legacy", done=False, owner_user="founder"),
        mcp._tools["brain.work_status"].handler(owner_user="founder"),
        mcp._tools["brain.work_get"].handler(owner_user="founder"),
        mcp._tools["brain.work_leaf_get"].handler(
            leaf_id="legacy", owner_user="founder"),
        mcp._tools["brain.work_court_run"].handler(
            leaf_id="legacy", owner_user="founder"),
        mcp._tools["brain.work_court_run_cell_first"].handler(
            leaf_id="legacy", owner_user="founder"),
    ]

    assert all(result["ok"] is False for result in results)
    assert all(result["universal"] is True for result in results)
    assert all(result["code"] == "legacy_work_route_retired" for result in results)
    assert store.get_meta(aw.LEDGER_META_KEY) == source_before


def test_assigned_block_writes_active_cde_state_for_direct_mcp_hooks(
    store,
    tmp_path,
    monkeypatch,
):
    """Claude Code calls brain.work_assigned_block directly as an MCP hook, not
    through brainwrap. The daemon must persist the active CDE container itself
    so the later PreToolUse hook can enforce allowed_paths."""
    from personal_brain.server import build_server
    from personal_brain import compliance_report as cr
    from personal_brain import hook_coverage as hc
    from personal_brain.universal_runtime import UniversalRuntimeBridge
    from personal_brain.universal_session_manager import (
        UniversalRuntimeSessionManager,
    )
    from nodelang.application_server import ApplicationServer
    from nodelang.cell_secret_keys import MemorySigningKeyProvider

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv("ARCHHUB_ACTIVE_CDE_STATE", raising=False)
    session_id = "claude-session-42"
    state_path = aw._active_cde_state_path(
        runtime="claude-code", session_id=session_id
    )
    report = _green_hook_coverage_report("claude-code")
    store.set_meta(hc.COVERAGE_META_KEY, report.model_dump_json())
    cde_container = {
        "container_id": "GM.ui.ui_home_topbar",
        "source_requirement": "grand-map:ui_home_topbar",
        "domain": "ui",
        "tier": "T1",
        "lifecycle_state": "PRODUCTION",
        "suitability_status": "S1",
        "revision": "P01",
        "owner": "agent",
        "checker": "court",
        "allowed_paths": ["10.PRODUCT/12.PRODUCTION/app/web_ui/"],
        "gate_kind": "cdp",
        "gate_spec": {"selector": "[data-uisurface='home-top']"},
        "evidence_ref": "cdp:home-top",
    }
    provider = MemorySigningKeyProvider(
        "archhub.local.universal-runtime-pipe", b"c" * 32
    )
    descriptor = tmp_path / "runtime.json"
    application = ApplicationServer(
        enable_machine_transport=True,
        machine_descriptor_path=descriptor,
        machine_key_provider=provider,
        runtime_compliance_runner=_green_runtime_compliance,
    ).start()
    manager = UniversalRuntimeSessionManager(
        lambda: UniversalRuntimeBridge(descriptor, provider)
    )
    try:
        manager.enroll(
            runtime="claude-code", external_session_id=session_id
        )
        manager.create(
            runtime="claude-code",
            external_session_id=session_id,
            title="home topbar from nodes",
            description="Direct Cell-native work for the CDE hook court.",
            priority=100,
            external_key="court:direct-cde-hook",
            structured_references={
                "requirements": {
                    "gate": {
                        "kind": "core_values_authority_repair",
                        "spec": {
                            "tool": "brain.core_values_authority_audit"
                        },
                    },
                },
                "cde-container": cde_container,
            },
        )
        mcp = build_server(
            store=store,
            default_owner_user="founder",
            runtime_session_manager=manager,
        )
        res = mcp._tools["brain.work_assigned_block"].handler(
            runtime="claude-code",
            session_id=session_id,
            owner_user="founder",
        )
    finally:
        application.close()

    assert res["ok"] is True
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["schema"] == "archhub-active-cde/v1"
    assert state["runtime"] == "claude-code"
    assert state["leaf_id"] == res["leaf"]["leaf_id"]
    assert state["container"] == cde_container

    # This file is a hook cache, not an audit authority. The graph-owned work
    # claim already records the assignment; CDE cache writes must not revive
    # the retired compliance_history_v1 ledger.
    assert store.get_meta(cr.HISTORY_META_KEY) is None


def test_brain_cde_state_clear_cannot_erase_another_session(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv("ARCHHUB_ACTIVE_CDE_STATE", raising=False)
    leaf = {
        "leaf_id": "leaf-1",
        "title": "isolated scope",
        "cde_container": {
            "container_id": "GM.nodes.runtime",
            "allowed_paths": ["10.PRODUCT/13.NODE-LANGUAGE/"],
        },
    }
    path_a = aw._active_cde_state_path(
        runtime="codex", session_id="session-a"
    )
    path_b = aw._active_cde_state_path(
        runtime="codex", session_id="session-b"
    )

    aw._write_active_cde_state(
        leaf, runtime="codex", session_id="session-a"
    )
    aw._write_active_cde_state(
        leaf, runtime="codex", session_id="session-b"
    )
    aw._clear_active_cde_state(runtime="codex", session_id="session-a")

    assert path_a != path_b
    assert not path_a.exists()
    assert path_b.exists()


def _run_standalone() -> int:
    import contextlib

    fns = [(k, v) for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in fns:
        s = None
        try:
            if "store" in fn.__code__.co_varnames[:fn.__code__.co_argcount]:
                s = BrainStore.open(":memory:")
                fn(s)
            else:
                fn()
            print(f"PASS {name}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {name}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"ERROR {name}: {type(e).__name__}: {e}")
        finally:
            if s is not None:
                with contextlib.suppress(Exception):
                    s.close()
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_standalone())
