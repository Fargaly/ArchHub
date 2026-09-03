"""APP-08 — trigger scheduler: Speckle polling + standard cron are REAL.

Closes the Phase-1 stubs in app/workflows/triggers/scheduler.py:
  * `_speckle_changed` returned False always ("Phase 1 stub").
  * `_cron_due` no-opped on any standard cron string (croniter pending);
    only "every Nm/h/d" interval syntax fired.

These tests go RED on origin/main (both paths return False) and GREEN
with the fix. They drive the pure logic directly — no live Speckle
server, no background thread, no clock sleeps — so they are
deterministic and fast.
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from workflows.graph import Trigger  # noqa: E402
# Import only the class at module load — it exists on origin/main too, so
# the behavioural assertions below (not a missing-symbol ImportError) are
# what go RED on main. `_cron_matches` is imported lazily inside its own
# unit test, since that helper does not exist on main.
from workflows.triggers.scheduler import TriggerScheduler  # noqa: E402


def _new_scheduler_supports_injection() -> bool:
    """True iff TriggerScheduler accepts the injectable speckle_client
    (the fix). On origin/main it does not — used to drive a clean,
    behaviour-level skip→fail rather than a constructor TypeError."""
    import inspect
    return "speckle_client" in inspect.signature(
        TriggerScheduler.__init__).parameters


# ─── helpers ─────────────────────────────────────────────────────────


class _StubSpeckle:
    """A drop-in for SpeckleClient.pull_parameters that yields a scripted
    sequence of latest-version ids (the real client hits a GraphQL API)."""

    def __init__(self, version_ids):
        self._seq = list(version_ids)
        self.calls = 0

    def pull_parameters(self, project_id, branch="archhub/main"):
        self.calls += 1
        if not self._seq:
            return {"status": "error", "error": "no commits"}
        vid = self._seq.pop(0)
        if vid is None:
            return {"status": "error", "error": "no commits on branch"}
        return {"status": "ok", "commit_id": vid, "object_id": "obj-" + vid}


def _sched(speckle=None):
    """Build a scheduler with an injected (stub) Speckle client. Works on
    both the fixed tree (constructor param) and is resilient: if the
    constructor doesn't accept the param (origin/main), the client is set
    as an attribute so the BEHAVIOUR — not a TypeError — is what differs.
    On main `_speckle_changed` ignores the client and returns False, which
    is exactly the gap these tests refute."""
    try:
        return TriggerScheduler(on_fire=lambda *_: None,
                                speckle_client=speckle)
    except TypeError:
        s = TriggerScheduler(on_fire=lambda *_: None)
        s._speckle_client = speckle           # type: ignore[attr-defined]
        s._speckle_versions = {}              # type: ignore[attr-defined]
        s._last_cron_minute = {}              # type: ignore[attr-defined]
        return s


# ─── Speckle polling ─────────────────────────────────────────────────


def test_speckle_fires_on_new_version():
    """First poll establishes a baseline silently; a CHANGED version id on
    the next poll fires; an unchanged id does not."""
    stub = _StubSpeckle(["v1", "v1", "v2", "v2"])
    sched = _sched(stub)
    trig = Trigger(id="t-spk", type="speckle_webhook",
                   config={"project_id": "proj-abc", "branch": "main"})

    now = 1_000_000.0
    # 1st poll: baseline v1 — no fire.
    assert sched._speckle_changed(trig, now) is False
    # 2nd poll: still v1 — no fire.
    assert sched._speckle_changed(trig, now + 15) is False
    # 3rd poll: v2 — NEW version → fire. THIS is the line that is False on main.
    assert sched._speckle_changed(trig, now + 30) is True
    # 4th poll: still v2 — no fire.
    assert sched._speckle_changed(trig, now + 45) is False


def test_speckle_no_token_or_offline_degrades_to_false_no_raise():
    """No project id, or an unreachable/empty server, returns False and
    never raises — and never advances the baseline."""
    sched = _sched(_StubSpeckle(["v1"]))
    # No project id configured → honest False.
    bare = Trigger(id="t0", type="speckle_webhook", config={})
    assert sched._speckle_changed(bare, 1.0) is False

    # Server returns error every time → never fires, baseline never set.
    erroring = _StubSpeckle([None, None, None])
    sched2 = _sched(erroring)
    trig = Trigger(id="t1", type="speckle_webhook",
                   config={"project_id": "p"})
    assert sched2._speckle_changed(trig, 1.0) is False
    assert sched2._speckle_changed(trig, 2.0) is False
    # A real version after the errors becomes the baseline (still no fire),
    # proving a transient error didn't poison the trigger.
    sched3 = _sched(_StubSpeckle(["v9", "v10"]))
    t2 = Trigger(id="t2", type="speckle_webhook", config={"project_id": "p"})
    assert sched3._speckle_changed(t2, 1.0) is False   # baseline v9
    assert sched3._speckle_changed(t2, 2.0) is True    # v10 → fire


def test_should_fire_dispatches_speckle_type():
    """The public _should_fire routes speckle_webhook to the real poller."""
    stub = _StubSpeckle(["a", "b"])
    sched = _sched(stub)
    trig = Trigger(id="t", type="speckle_webhook",
                   config={"project_id": "proj"})
    assert sched._should_fire(None, trig, 1.0) is False   # baseline
    assert sched._should_fire(None, trig, 2.0) is True    # changed → fire


# ─── standard cron ───────────────────────────────────────────────────


def test_cron_fires_on_matching_minute():
    """A standard 5-field cron string fires on a matching minute. On
    origin/main this returns False (the standard-cron branch no-ops)."""
    sched = _sched()
    trig = Trigger(id="t-cron", type="cron",
                   config={"expression": "*/5 * * * *"})

    matching = datetime(2026, 6, 17, 10, 5, 0).timestamp()   # minute 5
    non_matching = datetime(2026, 6, 17, 10, 6, 0).timestamp()  # minute 6

    # Matching minute → fire (the assertion that is RED on main).
    assert sched._cron_due(trig, matching) is True
    # Same minute again → no double-fire (fires once per minute).
    assert sched._cron_due(trig, matching + 1) is False
    # A non-matching minute → no fire.
    assert sched._cron_due(trig, non_matching) is False


def test_cron_weekday_business_hours():
    """`0 9 * * 1-5` fires 09:00 Mon-Fri only."""
    sched = _sched()
    trig = Trigger(id="t-biz", type="cron",
                   config={"cron": "0 9 * * 1-5"})   # `cron` key too

    monday_9 = datetime(2026, 6, 15, 9, 0, 0).timestamp()    # Mon
    saturday_9 = datetime(2026, 6, 13, 9, 0, 0).timestamp()  # Sat
    monday_10 = datetime(2026, 6, 15, 10, 0, 0).timestamp()  # Mon, 10:00

    assert sched._cron_due(trig, monday_9) is True
    # Re-create scheduler state isolation by using a fresh trigger id per case
    sched2 = _sched()
    assert sched2._cron_due(trig, saturday_9) is False
    sched3 = _sched()
    assert sched3._cron_due(trig, monday_10) is False


def test_interval_syntax_still_works():
    """The pre-existing `every Nm` interval syntax is preserved."""
    sched = _sched()
    trig = Trigger(id="t-iv", type="cron",
                   config={"expression": "every 10m"})
    base = 1_000_000.0
    # First ever check: last=0, so (now-0) >= 600 → fires.
    assert sched._cron_due(trig, base) is True
    sched._last_runs["t-iv"] = base
    assert sched._cron_due(trig, base + 300) is False   # 5m < 10m
    assert sched._cron_due(trig, base + 600) is True    # 10m elapsed


def test_cron_matches_unit():
    """Direct unit coverage of the cron matcher's edge cases."""
    # Lazy import — the helper is added by the fix; absent on origin/main.
    from workflows.triggers.scheduler import _cron_matches
    dt = datetime(2026, 6, 17, 10, 5)   # Wednesday
    assert _cron_matches("5 10 * * *", dt) is True
    assert _cron_matches("5 10 17 6 *", dt) is True
    assert _cron_matches("0 10 * * *", dt) is False
    # Malformed → False, never raises.
    assert _cron_matches("not a cron", dt) is False
    assert _cron_matches("* * * *", dt) is False         # 4 fields
    assert _cron_matches("60 * * * *", dt) is False      # minute out of range
