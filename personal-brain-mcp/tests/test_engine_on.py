"""Engine-ON regression guard (AgDR-0044 §1 / MAKE-IT-REAL-PLAN §1).

These tests assert the brain is an ENGINE, not just a registry of tools:

  1. start_workers spins up live Sync / Publish / Reflexion / Watchdog
     threads and the supervisor reports them alive.
  2. A real successful trace fed through brain.skill_mint (queue_skill_mint)
     MINTS a real, non-seed skill via reflect_on_trace AND moves the
     calibration Beta posterior off the 1.0/1.0 prior.
  3. The BRAIN_WORKERS=off toggle keeps the engine dormant.

Before the §1 wire, (1) never started any thread and (2) persisted a trace
but never reflected — so no live trace ever minted a skill and α/β stayed
frozen. A regression to either state fails here.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

import pytest

from personal_brain.models import Provenance, Scope, Skill
from personal_brain.server import queue_skill_mint
from personal_brain.storage import BrainStore
from personal_brain import workers as workers_mod


def _prov():
    return Provenance(
        contributing_agent="claude-opus-4-8",
        contributing_user="founder",
        created_at=datetime.now(timezone.utc),
    )


def _seed_one_skill(store: BrainStore) -> None:
    """One unrelated seed skill so novelty isn't a trivial 1.0 cold-start
    and dedupe has something to compare against."""
    store.upsert_skill(Skill(
        id="seed-unrelated",
        name="notion_summarise",
        description=(
            "Read a Notion page by URL or id and produce a five bullet "
            "executive summary saved back to the same workspace as a child page."
        ),
        triggers=["summarize notion", "notion summary"],
        requires_mcps=["notion-mcp"],
        body="# Notion summarise\n1. fetch\n2. summarise\n3. create_page",
        examples=[{"input": "summarize notion page", "output": "summary"}],
        owner_user="founder",
        provenance=_prov(),
    ))


def _real_trace() -> dict:
    """A trace that looks like a genuine successful Revit takeoff flow —
    distinct tool family from the seed skill so it should mint NEW."""
    return {
        "trace_id": "trace-engine-on-1",
        "session_id": "sess-1",
        "user_message": "Give me the wall takeoff for Tower-A and export it",
        "tool_calls": [
            {"name": "revit_info", "args": {"doc": "Tower-A"}, "status": "ok"},
            {"name": "revit_execute_csharp",
             "args": {"script": "count walls"}, "status": "ok"},
            {"name": "revit_export_schedule",
             "args": {"fmt": "csv"}, "status": "ok"},
        ],
        "outcome": "success",
    }


def test_start_workers_brings_engine_alive(monkeypatch):
    # The personal-cloud worker reads its token from env/cloud.json — clear the
    # env so it comes up signed-out (inert) deterministically on any host.
    monkeypatch.delenv("ARCHHUB_CLOUD_TOKEN", raising=False)
    monkeypatch.delenv("ARCHHUB_CLOUD_URL", raising=False)
    store = BrainStore.open(":memory:")
    try:
        sup = workers_mod.start_workers(store, force=True)
        assert sup is not None, "force-start must return a supervisor"
        # Give threads a beat to come up.
        deadline = time.time() + 5.0
        while time.time() < deadline:
            st = sup.status()
            w = st["workers"]
            if (w["reflexion"]["alive"] and w["sync"]["alive"]
                    and w["publish"]["alive"] and w["watchdog"]["alive"]
                    and w["personal_cloud"]["alive"]):
                break
            time.sleep(0.05)
        st = sup.status()
        w = st["workers"]
        assert w["reflexion"]["alive"], f"reflexion not alive: {st}"
        assert w["sync"]["alive"], f"sync worker not alive: {st}"
        assert w["publish"]["alive"], f"publish worker not alive: {st}"
        assert w["watchdog"]["alive"], f"watchdog not alive: {st}"
        # Personal cross-device cloud sync must come up ALONGSIDE the firm sync
        # worker (additive) and be inert/signed-out with no token configured.
        assert w["personal_cloud"]["alive"], f"personal_cloud not alive: {st}"
        assert w["personal_cloud"]["signed_in"] is False, (
            f"personal_cloud should be signed-out with no token: {st}")
        assert not st["errors"], f"engine start errors: {st['errors']}"
    finally:
        workers_mod.stop_workers(store)
        store.close()


def test_real_trace_mints_skill_and_moves_calibration():
    store = BrainStore.open(":memory:")
    try:
        _seed_one_skill(store)
        skills_before = store.count_skills()

        # Calibration starts at the 1.0/1.0 Beta prior.
        assert store.get_meta("calibration_v1") is None

        result = queue_skill_mint(
            store=store,
            trace=_real_trace(),
            outcome="success",
            owner_user="founder",
            contributing_agent="claude-opus-4-8",
            session_id="sess-1",
        )

        # A real skill must have been minted from the live trace.
        assert result.queued is True, result.reason
        assert result.immediate_skill is not None, (
            f"no skill minted from real trace: {result.reason}"
        )
        minted = result.immediate_skill

        # The new skill is in the store and is NON-SEED (provenance carries
        # the trace id + contributing agent; it is not one of the backfill
        # 0/0 seeds).
        skills_after = store.count_skills()
        assert skills_after == skills_before + 1, (
            f"expected exactly one new skill, before={skills_before} "
            f"after={skills_after}"
        )
        persisted = store.get_skill(minted.id)
        assert persisted is not None, "minted skill not persisted to store"
        assert persisted.provenance.trace_id == "trace-engine-on-1", (
            "minted skill must carry the originating trace id (non-seed proof)"
        )
        assert persisted.id != "seed-unrelated"

        # Calibration moved OFF the 1.0/1.0 prior.
        import json
        calib = json.loads(store.get_meta("calibration_v1"))
        moved = (calib["alpha"] != 1.0) or (calib["beta"] != 1.0)
        assert moved, (
            f"calibration alpha/beta did not move off prior: "
            f"alpha={calib['alpha']} beta={calib['beta']}"
        )
        # A honed-and-published skill is a 'retained' observation → alpha.
        assert calib["alpha"] >= 2.0, (
            f"expected alpha to advance on a retained mint, got {calib['alpha']}"
        )
    finally:
        store.close()


def test_workers_toggle_off(monkeypatch):
    monkeypatch.setenv("BRAIN_WORKERS", "0")
    store = BrainStore.open(":memory:")
    try:
        assert workers_mod.workers_enabled() is False
        sup = workers_mod.start_workers(store)  # not forced
        assert sup is None, "engine must stay dormant when BRAIN_WORKERS=0"
    finally:
        workers_mod.stop_workers(store)
        store.close()
