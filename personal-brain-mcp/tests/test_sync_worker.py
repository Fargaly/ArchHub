"""Slice 10 — scheduled sync worker tests.

CRITICAL test: TWO BrainStore instances + ONE JsonFileTransport.
Device A writes a firm-scope fragment → device B ticks the worker →
device B's brain.db now contains device A's fragment.

This is the END-TO-END "shared firm memory" verification that was
missing before (per ANTI-LIE MANDATE).
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone

import pytest

from personal_brain.firm import accept_invite_token, create_firm, create_invite_token
from personal_brain.hlc import reset_device_clock
from personal_brain.models import (
    Confidence,
    Fragment,
    FragmentKind,
    Provenance,
    Scope,
    Skill,
    Visibility,
)
from personal_brain.storage import BrainStore
from personal_brain.sync import JsonFileTransport
from personal_brain.sync_worker import SyncWorker


# ─────────────────────── fixtures ──────────────────────────────────────


def _firm_fragment(fid: str, text: str, owner: str, firm_id: str):
    return Fragment(
        id=fid, kind=FragmentKind.FACT, text=text,
        scope=Scope.FIRM, visibility=Visibility.SHARED_COMPANY,
        owner_user=owner, firm_id=firm_id,
        confidence=Confidence.EXTRACTED,
        provenance=Provenance(
            contributing_agent="test", contributing_user=owner,
            created_at=datetime.now(timezone.utc),
        ),
    )


@pytest.fixture(autouse=True)
def fresh_hlc():
    reset_device_clock()
    yield
    reset_device_clock()


# ─────────────────────── single-device tick ────────────────────────────


def test_worker_tick_pushes_local_fragments_to_transport(tmp_path):
    s = BrainStore.open(":memory:")
    t = JsonFileTransport(tmp_path / "shared.json")
    s.write_fragment(_firm_fragment("f-A", "Tower-A wall takeoff",
                                       "fargaly", "firm-x"))
    w = SyncWorker(s, t, interval_s=60, device_id="dev-A")
    result = w.tick()
    assert result.ok
    assert result.pushed_fragments >= 1
    pulled = t.pull()
    assert pulled is not None
    ids = {f.get("id") for f in pulled.get("fragments") or []}
    assert "f-A" in ids


def test_worker_tick_pulls_remote_fragment_into_local_store(tmp_path):
    """Device A writes; device B's worker pulls + writes into B's store."""
    transport_path = tmp_path / "shared.json"
    a = BrainStore.open(":memory:")
    b = BrainStore.open(":memory:")
    t_a = JsonFileTransport(transport_path)
    t_b = JsonFileTransport(transport_path)

    a.write_fragment(_firm_fragment("from-A", "fact made on device A",
                                       "alice", "firm-x"))

    # Device A pushes
    wa = SyncWorker(a, t_a, interval_s=60, device_id="dev-A")
    wa.tick()

    # Device B pulls + merges
    assert b.count_fragments() == 0
    wb = SyncWorker(b, t_b, interval_s=60, device_id="dev-B",
                     owner_user="bob")
    res_b = wb.tick()

    # Critical assertion: device B now has device A's fragment
    fetched = b.get_fragment("from-A")
    assert fetched is not None, f"device B should have from-A; res={res_b}"
    assert fetched.text == "fact made on device A"
    assert fetched.scope == Scope.FIRM
    assert res_b.applied_to_local >= 1


def test_worker_bidirectional_merge(tmp_path):
    """Both devices push different fragments → both end up with the union."""
    transport_path = tmp_path / "shared.json"
    a = BrainStore.open(":memory:")
    b = BrainStore.open(":memory:")
    t_a = JsonFileTransport(transport_path)
    t_b = JsonFileTransport(transport_path)

    a.write_fragment(_firm_fragment("fA", "from A", "alice", "firm-x"))
    b.write_fragment(_firm_fragment("fB", "from B", "bob", "firm-x"))

    # A pushes
    SyncWorker(a, t_a, interval_s=60, device_id="A").tick()
    # B pulls A's + pushes its own
    SyncWorker(b, t_b, interval_s=60, device_id="B").tick()
    # A pulls B's
    SyncWorker(a, t_a, interval_s=60, device_id="A").tick()

    assert a.get_fragment("fB") is not None
    assert b.get_fragment("fA") is not None


def test_worker_handles_empty_transport(tmp_path):
    """Empty transport → no remote → just push local."""
    s = BrainStore.open(":memory:")
    t = JsonFileTransport(tmp_path / "empty.json")
    w = SyncWorker(s, t, interval_s=60)
    res = w.tick()
    assert res.ok
    assert res.remote_fragments == 0


def test_worker_status_reflects_state(tmp_path):
    s = BrainStore.open(":memory:")
    t = JsonFileTransport(tmp_path / "x.json")
    w = SyncWorker(s, t, interval_s=60)
    assert not w.status()["running"]
    w.tick()
    st = w.status()
    assert st["cycle_count"] == 1
    assert st["last_result"]["ok"] is True
    assert st["transport"] == "json-file"


def test_worker_skill_sync_across_devices(tmp_path):
    """Firm-scope skill on device A appears on device B."""
    transport_path = tmp_path / "skills.json"
    a = BrainStore.open(":memory:")
    b = BrainStore.open(":memory:")
    t_a = JsonFileTransport(transport_path)
    t_b = JsonFileTransport(transport_path)

    skill = Skill(
        id="sk-firm-revit", name="firm_revit_takeoff",
        description=(
            "Firm-shared Revit wall + floor + room takeoff that emits "
            "a CSV the QS team can paste into their cost sheet."
        ),
        triggers=["firm takeoff", "QS export"],
        requires_mcps=["revit-mcp"],
        body="# firm takeoff",
        examples=[{"input": "x", "output": "y"}],
        scope=Scope.FIRM,
        visibility=Visibility.SHARED_COMPANY,
        owner_user="alice",
        provenance=Provenance(
            contributing_agent="test", contributing_user="alice",
        ),
    )
    a.upsert_skill(skill)

    SyncWorker(a, t_a, interval_s=60, device_id="A").tick()
    SyncWorker(b, t_b, interval_s=60, device_id="B").tick()

    fetched = b.get_skill("firm_revit_takeoff")
    assert fetched is not None
    assert fetched.scope == Scope.FIRM


def test_worker_async_loop_runs_and_stops(tmp_path):
    s = BrainStore.open(":memory:")
    t = JsonFileTransport(tmp_path / "x.json")
    s.write_fragment(_firm_fragment("f1", "x", "alice", "firm-x"))
    w = SyncWorker(s, t, interval_s=0.1, device_id="A")
    w.start()
    try:
        # Wait for at least one cycle
        for _ in range(20):
            if w.status()["cycle_count"] > 0:
                break
            time.sleep(0.05)
        assert w.status()["cycle_count"] >= 1
    finally:
        w.stop(timeout_s=1.0)
    assert not w.status()["running"]


def test_worker_does_not_sync_user_scope_of_other_owner(tmp_path):
    """User-scope fragments are owner-only; worker must not leak them
    across owners even if both write to same transport."""
    transport_path = tmp_path / "shared.json"
    a = BrainStore.open(":memory:")
    b = BrainStore.open(":memory:")
    t_a = JsonFileTransport(transport_path)
    t_b = JsonFileTransport(transport_path)

    a.write_fragment(Fragment(
        id="alice-private", kind=FragmentKind.FACT,
        text="alice private", scope=Scope.USER,
        owner_user="alice",
        provenance=Provenance(contributing_agent="t",
                                contributing_user="alice"),
    ))

    # Worker scope defaults to [FIRM, PROJECT] — USER-scope NOT pushed
    SyncWorker(a, t_a, interval_s=60, device_id="A",
                owner_user="alice").tick()
    SyncWorker(b, t_b, interval_s=60, device_id="B",
                owner_user="bob").tick()
    assert b.get_fragment("alice-private") is None


def test_worker_persists_last_sync_metadata(tmp_path):
    s = BrainStore.open(":memory:")
    t = JsonFileTransport(tmp_path / "x.json")
    w = SyncWorker(s, t, interval_s=60)
    w.tick()
    last = s.get_meta("sync_worker.last_sync_ts")
    assert last is not None and last
    result_json = s.get_meta("sync_worker.last_result_json")
    assert result_json
    parsed = json.loads(result_json)
    assert parsed["ok"] is True


def test_worker_firm_integration_end_to_end(tmp_path):
    """Full firm round-trip:
        admin device creates firm + invite
        seat device accepts invite
        seat device writes a firm-scope fact
        sync round-trip — admin sees seat's fact
    """
    transport_path = tmp_path / "firm.json"
    admin = BrainStore.open(":memory:")
    seat = BrainStore.open(":memory:")

    # Step 1: admin creates firm
    identity = create_firm(admin, name="ArchHub Studio",
                             created_by="alice-admin")

    # Step 2: seat accepts invite
    envelope = create_invite_token(admin, role="seat")
    accept_invite_token(seat, envelope=envelope, user_id="bob-seat")

    # Step 3: seat writes a firm-scope fact
    seat.write_fragment(Fragment(
        id="firm-rule-1", kind=FragmentKind.FACT,
        text="Tower-A wall thickness is 200mm per firm spec",
        scope=Scope.FIRM, visibility=Visibility.SHARED_COMPANY,
        owner_user="bob-seat", firm_id=identity.firm_id,
        provenance=Provenance(contributing_agent="t",
                                contributing_user="bob-seat"),
    ))

    # Step 4: sync
    t_admin = JsonFileTransport(transport_path)
    t_seat = JsonFileTransport(transport_path)
    SyncWorker(seat, t_seat, interval_s=60, device_id="seat-dev").tick()
    SyncWorker(admin, t_admin, interval_s=60, device_id="admin-dev").tick()

    # Admin sees seat's firm-scope fact
    fetched = admin.get_fragment("firm-rule-1")
    assert fetched is not None
    assert fetched.text == "Tower-A wall thickness is 200mm per firm spec"
    assert fetched.scope == Scope.FIRM
    assert fetched.firm_id == identity.firm_id
