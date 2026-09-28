"""Courts: a forget really deletes the CLOUD copy, against the real server code.

The server here is cloud_backend brain_replica.py itself -- ``BrainReplica``
with its own schema, its ``apply_delta`` (last-writer-wins, ``WHERE
excluded.hlc > fragments.hlc``) and its ``export_delta`` -- composed exactly as
main.py ``/v1/brain/sync`` composes them, over a replica in a temporary folder.
No network, no token, no live data. Each court reads the cloud row back from
the replica's own sqlite file; local tracking alone proves nothing.
"""
from __future__ import annotations

import sqlite3

from cloud_backend.brain_replica import BrainReplica
from nodelang.brain_cloud_sync import SyncCursor, sync_once
from nodelang.cell_brain_governance import classify
from nodelang.cell_brain_memory import (
    FORGOTTEN,
    LIVE,
    Memory,
    forget,
    merge_memories,
    recall_memory,
    remember,
)
from nodelang.cell_session_state import open_session
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore

FOUNDER = "app:users:founder"
SESSION = "app:sessions:founder"
ACCOUNT = "u_founder"
RELEASABLE = ("personal-files", "instances")


class RealCloud:
    """cloud_backend brain_replica.py behind the /v1/brain/sync composition."""

    def __init__(self, root):
        self.root = root
        self.posts = 0

    def post(self, payload):
        self.posts += 1
        replica = BrainReplica.open(user_id=ACCOUNT, root=self.root)
        result = replica.apply_delta(payload.get("delta") or {})
        merged = replica.export_delta(since_hlc=(payload.get("since_hlc") or "").strip())
        return {"accepted": result["accepted"], "rejected": result["rejected"],
                "new_hlc": result["new_hlc"], "merged": merged,
                "firm_keys": [], "community_keys": []}

    def row(self, fragment_id):
        db = sqlite3.connect(self.root / ACCOUNT / "brain.db")
        db.row_factory = sqlite3.Row
        try:
            found = db.execute("SELECT id, text, valid_until, hlc FROM fragments WHERE id = ?",
                               (fragment_id,)).fetchone()
        finally:
            db.close()
        return dict(found) if found else None


def _device():
    store = CellStore()
    store.commit(store.revision, create=(Cell(FOUNDER, NULL_CELL_ID, NULL_CELL_ID, b"founder"),))
    open_session(store, session_root=SESSION, owner_root=FOUNDER)
    return store


def _sync(store, cloud, cursor=None, post=None):
    return sync_once(store, session_root=SESSION, owner_user=ACCOUNT,
                     cursor=cursor or SyncCursor(), post=post or cloud.post)


def _classify(store, fragment_id, origin, clock):
    classify(store, session_root=SESSION, fragment_id=fragment_id, data_class=RELEASABLE[0],
             stratum=RELEASABLE[1], origin=origin, clock=clock)


def _assert_cloud_forgot(cloud, fragment_id, secret):
    row = cloud.row(fragment_id)
    assert row is not None
    assert secret not in (row["text"] or ""), "the cloud still serves the forgotten text: %r" % row
    assert row["text"] == "" and row["valid_until"] is not None


SEALED = ("security-details", "instances")


def test_taking_back_under_a_newer_text_deletes_the_cloud_copy(tmp_path):
    """Ping's clocks: text (1000,A), classification (20,B); taking the memory
    back at (50,B) must blank the cloud row, whose HLC 0000000000001000.A is
    newer than the part that changed. (A state part below its own text part
    does not survive a sync -- the echo lands state at the text clock -- so the
    reachable take-back at (50,B) is the sealing.)"""
    cloud, device = RealCloud(tmp_path), _device()
    remember(device, session_root=SESSION, fragment_id="fact-fee", text="fee is 4 percent",
             kind="fact", origin="B", clock=10)
    _classify(device, "fact-fee", "B", 20)
    merge_memories(device, (Memory("fact-fee", "fee is 4.5 percent", "fact", "extracted",
                                   FOUNDER, LIVE, "A", 1000, "A", 1000),),
                   session_root=SESSION)
    first = _sync(device, cloud)
    assert cloud.row("fact-fee")["text"] == "fee is 4.5 percent"
    assert cloud.row("fact-fee")["hlc"] == "0000000000001000.A"
    classify(device, session_root=SESSION, fragment_id="fact-fee", data_class=SEALED[0],
             stratum=SEALED[1], origin="B", clock=50)
    report = _sync(device, cloud, first.cursor)
    _assert_cloud_forgot(cloud, "fact-fee", "4.5")
    assert report.retracted == 1
    assert "fact-fee" not in report.cursor.released
    assert _sync(device, cloud, report.cursor).retracted == 0
    _assert_cloud_forgot(cloud, "fact-fee", "4.5")

def test_a_forget_at_the_same_clock_as_the_last_seen_row_deletes_the_cloud_copy(tmp_path):
    """The forget's clock EQUALS the clock the cloud row and the cursor already
    hold for this origin (classified at 40, forgotten at 40)."""
    cloud, device = RealCloud(tmp_path), _device()
    remember(device, session_root=SESSION, fragment_id="fact-sheet", text="client wants A1 sheets",
             kind="fact", origin="desktop", clock=30)
    _classify(device, "fact-sheet", "desktop", 40)
    first = _sync(device, cloud)
    assert cloud.row("fact-sheet")["hlc"] == "0000000000000040.desktop"
    forget(device, session_root=SESSION, fragment_id="fact-sheet", origin="desktop", clock=40)
    assert recall_memory(device.snapshot(), "fact-sheet", session_root=SESSION).state == FORGOTTEN
    report = _sync(device, cloud, first.cursor)
    _assert_cloud_forgot(cloud, "fact-sheet", "A1")
    assert "fact-sheet" not in report.cursor.released


def test_tracking_stays_until_the_cloud_confirms_the_deletion(tmp_path):
    """A server that answers but does not store the retraction must leave the
    id tracked, so the next sync takes it back for real."""
    cloud, device = RealCloud(tmp_path), _device()
    remember(device, session_root=SESSION, fragment_id="fact-core", text="core at grid C4",
             kind="fact", origin="desktop", clock=10)
    _classify(device, "fact-core", "desktop", 10)
    first = _sync(device, cloud)
    forget(device, session_root=SESSION, fragment_id="fact-core", origin="desktop", clock=20)

    def dropped(payload):
        return cloud.post(dict(payload, delta={"fragments": [], "wiring": []}))

    lost = _sync(device, cloud, first.cursor, post=dropped)
    assert cloud.row("fact-core")["text"] == "core at grid C4"
    assert "fact-core" in lost.cursor.released
    assert lost.retracted == 0
    again = _sync(device, cloud, lost.cursor)
    _assert_cloud_forgot(cloud, "fact-core", "C4")
    assert "fact-core" not in again.cursor.released

def test_a_stale_view_never_restamps_over_a_newer_row(tmp_path):
    """Verifier probe on v2: A's cursor still remembered the row at 40.desktop
    when B had already replaced it with 41.B. A's later, OLDER text edit was
    stamped above the stale view (41.desktop), beat B in the cloud, and B --
    whose pull cursor was past 41 -- never saw it: the devices diverged. A
    retry may be stamped only above the row seen in the same sync."""
    cloud, desktop, laptop = RealCloud(tmp_path), _device(), _device()
    remember(desktop, session_root=SESSION, fragment_id="fact-rate", text="rate 400",
             kind="fact", origin="desktop", clock=30)
    _classify(desktop, "fact-rate", "desktop", 40)
    a = _sync(desktop, cloud)
    assert cloud.row("fact-rate")["hlc"] == "0000000000000040.desktop"
    b = _sync(laptop, cloud)
    remember(laptop, session_root=SESSION, fragment_id="fact-rate", text="rate 450",
             kind="fact", origin="B", clock=41)
    b = _sync(laptop, cloud, b.cursor)
    assert cloud.row("fact-rate")["text"] == "rate 450"
    remember(desktop, session_root=SESSION, fragment_id="fact-rate", text="rate 380",
             kind="fact", origin="x", clock=35)
    a = _sync(desktop, cloud, a.cursor)
    b = _sync(laptop, cloud, b.cursor)
    a = _sync(desktop, cloud, a.cursor)
    assert cloud.row("fact-rate")["text"] == "rate 450", "the newer edit keeps the cloud"
    for device in (desktop, laptop):
        assert recall_memory(device.snapshot(), "fact-rate", session_root=SESSION).text == "rate 450"
