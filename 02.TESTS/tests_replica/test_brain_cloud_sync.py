"""Courts for personal cloud sync over graph-held, governed memory.

The server here is a faithful in-memory copy of the cloud replica: the
``fragments`` table from cloud_backend brain_replica.py ``_SCHEMA``, its
last-writer-wins upsert (``WHERE excluded.hlc > fragments.hlc``) and its export
query copied verbatim, and the ``/v1/brain/sync`` response shape from
cloud_backend main.py. No network, no token, no live data, no file.

Rebased on the session-bound memory and the governance layer (d810889): only
what ``may_release(..., "personal")`` allows leaves a device, and a forget or a
sealing of something already released is taken back without its content.
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from nodelang.brain_cloud_sync import SyncCursor, encode_hlc, sync_once
from nodelang.cell_brain_governance import classification, classify
from nodelang.cell_brain_memory import (
    FORGOTTEN,
    LIVE,
    forget,
    memories,
    recall_memory,
    remember,
)
from nodelang.cell_session_state import ACTIVE, CLOSED, move_to, open_session
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell

FOUNDER = "app:users:founder"
COLLEAGUE = "app:users:colleague"
S_FOUNDER = "app:sessions:founder"
S_COLLEAGUE = "app:sessions:colleague"
ACCOUNT = "u_founder"
RELEASABLE = ("personal-files", "instances")   # ceiling personal: syncs to own devices
SEALED = ("security-details", "instances")     # never leaves the device

REPLICA_FRAGMENTS_DDL = """
CREATE TABLE fragments (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    text TEXT NOT NULL,
    subject TEXT,
    predicate TEXT,
    object TEXT,
    scope TEXT NOT NULL DEFAULT 'user',
    visibility TEXT NOT NULL DEFAULT 'private',
    owner_user TEXT NOT NULL,
    project_id TEXT,
    firm_id TEXT,
    confidence TEXT NOT NULL DEFAULT 'extracted',
    provenance_json TEXT NOT NULL DEFAULT '{}',
    valid_from TEXT,
    valid_until TEXT,
    extra_json TEXT,
    hlc TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
)
"""

REPLICA_UPSERT = (
    "INSERT INTO fragments"
    " (id, kind, text, subject, predicate, object,"
    "  scope, visibility, owner_user,"
    "  project_id, firm_id, confidence,"
    "  provenance_json, valid_from, valid_until,"
    "  extra_json, hlc)"
    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
    " ON CONFLICT(id) DO UPDATE SET"
    "   text = excluded.text,"
    "   subject = excluded.subject,"
    "   predicate = excluded.predicate,"
    "   object = excluded.object,"
    "   scope = excluded.scope,"
    "   visibility = excluded.visibility,"
    "   owner_user = excluded.owner_user,"
    "   confidence = excluded.confidence,"
    "   provenance_json = excluded.provenance_json,"
    "   valid_from = excluded.valid_from,"
    "   valid_until = excluded.valid_until,"
    "   extra_json = excluded.extra_json,"
    "   hlc = excluded.hlc,"
    "   updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')"
    " WHERE excluded.hlc > fragments.hlc"
)

REPLICA_EXPORT = (
    "SELECT id, kind, text, subject, predicate, object,"
    " scope, visibility, owner_user, project_id, firm_id,"
    " confidence, provenance_json, valid_from, valid_until,"
    " extra_json, hlc, created_at, updated_at"
    " FROM fragments WHERE hlc > ? ORDER BY hlc ASC"
)


class ReplicaCopy:
    """The private per-user replica and its /v1/brain/sync handler."""

    def __init__(self, user_id=ACCOUNT, now_ms=0):
        self.user_id = user_id
        self.now_ms = now_ms
        self.last_hlc = "0000000000000000.00000000"
        self.reject_ids = set()
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.execute(REPLICA_FRAGMENTS_DDL)

    def seed(self, **row):
        frag = dict(row)
        frag.setdefault("scope", "user")
        frag.setdefault("provenance", {})
        frag.setdefault("extra", {})
        self._write(frag, frag["hlc"])
        self.db.commit()

    def _write(self, frag, hlc):
        self.db.execute(REPLICA_UPSERT, (
            frag.get("id"),
            frag.get("kind") or "fact",
            frag.get("text") or "",
            frag.get("subject"),
            frag.get("predicate"),
            frag.get("object"),
            frag.get("scope") or "user",
            frag.get("visibility") or "private",
            self.user_id,                       # owner_force on the private replica
            frag.get("project_id"),
            frag.get("firm_id"),
            frag.get("confidence") or "extracted",
            json.dumps(frag.get("provenance") or {}),
            frag.get("valid_from"),
            frag.get("valid_until"),
            json.dumps(frag.get("extra") or {}),
            hlc,
        ))

    def post(self, payload):
        delta = payload.get("delta") or {}
        accepted, rejected = 0, []
        max_hlc = self.last_hlc
        new_hlc = "%016d.%08x" % (self.now_ms, 0)
        for frag in delta.get("fragments") or []:
            if frag.get("id") in self.reject_ids:
                rejected.append({"id": frag.get("id"), "reason": "held back by court"})
                continue
            hlc = frag.get("hlc") or new_hlc
            if hlc > max_hlc:
                max_hlc = hlc
            self._write(frag, hlc)
            accepted += 1
        self.db.commit()
        self.last_hlc = max_hlc if max_hlc > new_hlc else new_hlc
        since = payload.get("since_hlc") or "0000000000000000.00000000"
        rows = []
        for record in self.db.execute(REPLICA_EXPORT, (since,)).fetchall():
            row = dict(record)
            row["provenance"] = json.loads(row.pop("provenance_json") or "{}")
            row["extra"] = json.loads(row.pop("extra_json") or "{}")
            rows.append(row)
        return {"accepted": accepted, "rejected": rejected, "new_hlc": self.last_hlc,
                "merged": {"fragments": rows, "wiring": [], "new_hlc": self.last_hlc},
                "firm_keys": [], "community_keys": []}

    def dump(self):
        return [tuple(r) for r in self.db.execute("SELECT * FROM fragments ORDER BY id")]

    def row(self, fragment_id):
        found = self.db.execute("SELECT * FROM fragments WHERE id = ?", (fragment_id,)).fetchone()
        return dict(found) if found else None


def _device():
    store = CellStore()
    store.commit(store.revision, create=(
        Cell(FOUNDER, NULL_CELL_ID, NULL_CELL_ID, b"founder"),
        Cell(COLLEAGUE, NULL_CELL_ID, NULL_CELL_ID, b"colleague"),
    ))
    open_session(store, session_root=S_FOUNDER, owner_root=FOUNDER)
    open_session(store, session_root=S_COLLEAGUE, owner_root=COLLEAGUE)
    return store


def _sync(store, cloud, cursor=None, session=S_FOUNDER, **options):
    return sync_once(store, session_root=session, owner_user=ACCOUNT,
                     cursor=cursor or SyncCursor(), post=cloud.post, **options)


def _file(store, fragment_id, filed, clock, origin="desktop", session=S_FOUNDER):
    classify(store, session_root=session, fragment_id=fragment_id, data_class=filed[0],
             stratum=filed[1], origin=origin, clock=clock)


def _remember(store, fragment_id, text, clock, origin="desktop", kind="fact",
              filed=RELEASABLE, session=S_FOUNDER):
    remember(store, session_root=session, fragment_id=fragment_id, text=text, kind=kind,
             origin=origin, clock=clock)
    if filed is not None:
        _file(store, fragment_id, filed, clock, origin, session)


def _recall(store, fragment_id, session=S_FOUNDER):
    return recall_memory(store.snapshot(), fragment_id, session_root=session)


def _classification(store, fragment_id, session=S_FOUNDER):
    return classification(store.snapshot(), session_root=session, fragment_id=fragment_id)


def test_a_releasable_memory_reaches_the_server_with_its_classification():
    desktop, cloud = _device(), ReplicaCopy()
    _remember(desktop, "fact-rate", "site rate 450", 10)
    report = _sync(desktop, cloud)
    assert (report.pushed, report.retracted) == (1, 0)
    row = cloud.row("fact-rate")
    assert row["text"] == "site rate 450" and row["valid_until"] is None
    assert row["hlc"] == encode_hlc(10, "desktop")
    parts = json.loads(row["extra_json"])["brain_memory"]
    assert parts["classification"]["value"] == "personal-files|instances"


@pytest.mark.parametrize("filed", (None, SEALED))
def test_unclassified_and_sealed_memories_never_leave_the_device(filed):
    desktop, cloud = _device(), ReplicaCopy()
    _remember(desktop, "fact-riser", "riser and server room positions", 10, filed=filed)
    report = _sync(desktop, cloud)
    assert (report.pushed, report.retracted) == (0, 0)
    assert cloud.dump() == []


def test_forgetting_a_released_memory_takes_it_back_without_its_text():
    desktop, laptop, cloud = _device(), _device(), ReplicaCopy()
    _remember(desktop, "fact-old", "client prefers A3 sheets", 10)
    cursor = _sync(desktop, cloud).cursor
    laptop_cursor = _sync(laptop, cloud).cursor
    assert _recall(laptop, "fact-old").state == LIVE
    forget(desktop, session_root=S_FOUNDER, fragment_id="fact-old", origin="desktop",
           clock=20)
    report = _sync(desktop, cloud, cursor)
    assert (report.pushed, report.retracted) == (0, 1)
    row = cloud.row("fact-old")
    assert row["text"] == "" and row["valid_until"] is not None
    assert "A3" not in json.dumps(row)
    assert row["hlc"] == encode_hlc(20, "desktop")
    _sync(laptop, cloud, laptop_cursor)
    kept = _recall(laptop, "fact-old")
    assert (kept.state, kept.text) == (FORGOTTEN, "client prefers A3 sheets")


def test_sealing_a_released_memory_blanks_the_server_and_seals_every_device():
    desktop, laptop, cloud = _device(), _device(), ReplicaCopy()
    _remember(desktop, "fact-core", "core riser layout for tower a", 10)
    cursor = _sync(desktop, cloud).cursor
    laptop_cursor = _sync(laptop, cloud).cursor
    assert _classification(laptop, "fact-core").ceiling == "personal"
    _file(desktop, "fact-core", SEALED, 30)
    report = _sync(desktop, cloud, cursor)
    assert (report.pushed, report.retracted) == (0, 1)
    row = cloud.row("fact-core")
    assert row["text"] == "" and "riser" not in json.dumps(row)
    laptop_cursor = _sync(laptop, cloud, laptop_cursor).cursor
    assert _classification(laptop, "fact-core").ceiling == "sealed"
    again = _sync(laptop, cloud, laptop_cursor)
    assert (again.pushed, again.retracted) == (0, 0)
    assert cloud.row("fact-core")["text"] == ""


def test_a_second_device_receives_the_memory_and_its_classification():
    desktop, laptop, cloud = _device(), _device(), ReplicaCopy()
    _remember(desktop, "fact-rate", "site rate 450", 10)
    _remember(desktop, "setup-revit", "revit broker listens locally", 20, kind="setup")
    _sync(desktop, cloud)
    report = _sync(laptop, cloud)
    assert report.pulled == 2
    for fragment_id in ("fact-rate", "setup-revit"):
        assert _recall(laptop, fragment_id) == _recall(desktop, fragment_id)
        assert _classification(laptop, fragment_id) == _classification(desktop, fragment_id)


def test_syncing_twice_changes_nothing_on_the_device_or_the_server():
    desktop, cloud = _device(), ReplicaCopy()
    _remember(desktop, "fact-rate", "site rate 450", 10)
    _remember(desktop, "setup-revit", "revit broker listens locally", 20, kind="setup")
    _remember(desktop, "fact-riser", "riser positions", 25, filed=SEALED)
    first = _sync(desktop, cloud)
    revision, rows = desktop.snapshot().revision, cloud.dump()
    second = _sync(desktop, cloud, first.cursor)
    assert desktop.snapshot().revision == revision
    assert cloud.dump() == rows
    assert (second.pushed, second.retracted, second.pulled) == (0, 0, 0)
    full = _sync(desktop, cloud, second.cursor, full_pull=True)
    assert desktop.snapshot().revision == revision
    assert cloud.dump() == rows
    assert full.pulled == 0 and full.unchanged == 2


def test_two_devices_converge_whatever_order_they_sync_in():
    desktop, laptop, cloud = _device(), _device(), ReplicaCopy()
    _remember(desktop, "fact-rate", "rate 400", 10, origin="desktop")
    _remember(laptop, "fact-rate", "rate 450", 20, origin="laptop")
    _remember(laptop, "fact-site", "site on the corniche", 25, origin="laptop")
    forget(desktop, session_root=S_FOUNDER, fragment_id="fact-rate", origin="desktop",
           clock=15)
    cursors = {"desktop": SyncCursor(), "laptop": SyncCursor()}
    for name, store in (("desktop", desktop), ("laptop", laptop),
                        ("desktop", desktop), ("laptop", laptop)):
        cursors[name] = _sync(store, cloud, cursors[name]).cursor
    for fragment_id in ("fact-rate", "fact-site"):
        assert _recall(desktop, fragment_id) == _recall(laptop, fragment_id)
        assert _classification(desktop, fragment_id) == _classification(laptop, fragment_id)
    rate = _recall(desktop, "fact-rate")
    assert rate.text == "rate 450" and rate.state == LIVE


def test_an_older_server_row_never_overwrites_a_newer_local_memory():
    desktop, cloud = _device(), ReplicaCopy()
    cloud.seed(id="fact-rate", kind="fact", text="rate 300 (old)",
               hlc="%016d.%s" % (5, "a1b2c3d4"))
    _remember(desktop, "fact-rate", "rate 450", 50)
    _sync(desktop, cloud)
    assert _recall(desktop, "fact-rate").text == "rate 450"
    assert cloud.row("fact-rate")["text"] == "rate 450"


def test_memory_the_legacy_client_left_arrives_sealed_until_it_is_filed():
    """Existing-data court: rows in the shape the legacy client pushed
    (personal_cloud_sync.py:693-714): no memory parts, skills wrapped as
    kind=skill, HLC <16-digit physical ms>.<hex8>."""
    laptop, cloud = _device(), ReplicaCopy()
    cloud.seed(id="fact-rate", kind="fact", text="site rate 450", confidence="extracted",
               hlc="0001788256800000.a1b2c3d4")
    cloud.seed(id="setup-revit", kind="setup", text="revit broker on 48885",
               confidence="inferred", hlc="0001788426000000.0badf00d")
    cloud.seed(id="skill:sk-1a2b", kind="skill", text="hatch walls",
               extra={"skill": {"name": "hatch-walls"}}, hlc="0001788426000001.00000001")
    cloud.seed(id="turn-9f2", kind="trace", text="tool call log",
               hlc="0001788426000002.00000002")
    cloud.seed(id="fact-leak", kind="fact", text="pass" + "word = hunter2hunter2",
               hlc="0001788426000003.00000003")
    report = _sync(laptop, cloud)
    rate = _recall(laptop, "fact-rate")
    assert (rate.text, rate.state, rate.text_clock, rate.text_origin) == (
        "site rate 450", LIVE, 1788256800000, "hlc:a1b2c3d4")
    assert _recall(laptop, "setup-revit").confidence == "inferred"
    assert {m.fragment_id for m in memories(laptop.snapshot(), session_root=S_FOUNDER)} == {
        "fact-rate", "setup-revit"}
    assert _classification(laptop, "fact-rate").ceiling == "sealed"
    assert report.skipped == {"kind:skill": 1, "kind:trace": 1, "looks-like-a-secret": 1}
    revision, rows = laptop.snapshot().revision, cloud.dump()
    again = _sync(laptop, cloud, report.cursor, full_pull=True)
    assert (again.pushed, again.retracted) == (0, 0)
    assert laptop.snapshot().revision == revision
    assert cloud.dump() == rows


def test_a_rejected_push_is_sent_again_even_when_a_later_one_was_accepted():
    desktop, cloud = _device(), ReplicaCopy()
    _remember(desktop, "fact-rate", "site rate 450", 10)
    _remember(desktop, "fact-site", "site on the corniche", 12)
    cloud.reject_ids = {"fact-rate"}
    first = _sync(desktop, cloud)
    assert first.rejected == ("fact-rate",)
    assert cloud.row("fact-rate") is None
    assert cloud.row("fact-site")["text"] == "site on the corniche"
    cloud.reject_ids = set()
    _sync(desktop, cloud, first.cursor)
    assert cloud.row("fact-rate")["text"] == "site rate 450"


def test_a_fast_clock_on_another_device_never_hides_a_local_edit():
    desktop, laptop, cloud = _device(), _device(), ReplicaCopy()
    _remember(desktop, "fact-early", "desktop pushed this first", 100, origin="desktop")
    cursor = _sync(desktop, cloud).cursor
    _remember(laptop, "fact-fast", "laptop clock runs ahead", 1_000_000, origin="laptop")
    _sync(laptop, cloud)
    cursor = _sync(desktop, cloud, cursor).cursor
    _remember(desktop, "fact-slow", "desktop clock runs behind", 900, origin="desktop")
    _sync(desktop, cloud, cursor)
    assert cloud.row("fact-slow")["text"] == "desktop clock runs behind"


def test_an_offline_device_is_caught_up_by_a_full_pull():
    """The server cursor is the server's clock. An edit made offline with an
    older clock is below another device's cursor, so an incremental pull misses
    it and the periodic full pull must catch it."""
    desktop, laptop, cloud = _device(), _device(), ReplicaCopy(now_ms=1_000_000)
    cursor = _sync(desktop, cloud).cursor
    _remember(laptop, "fact-offline", "written on the plane", 500, origin="laptop")
    _sync(laptop, cloud)
    missed = _sync(desktop, cloud, cursor)
    assert _recall(desktop, "fact-offline") is None
    _sync(desktop, cloud, missed.cursor, full_pull=True)
    assert _recall(desktop, "fact-offline").text == "written on the plane"


def test_sync_carries_only_the_session_owners_memory():
    desktop, cloud = _device(), ReplicaCopy(user_id="u_colleague")
    _remember(desktop, "fact-founder", "founder only note", 10)
    _remember(desktop, "fact-colleague", "colleague note", 11, session=S_COLLEAGUE)
    report = _sync(desktop, cloud, session=S_COLLEAGUE)
    assert report.pushed == 1
    assert [row[0] for row in cloud.dump()] == ["fact-colleague"]


@pytest.mark.parametrize("session", (FOUNDER, "app:sessions:nobody", None))
def test_only_an_open_session_can_sync(session):
    desktop = _device()
    _remember(desktop, "fact-rate", "site rate 450", 10)
    calls = []
    with pytest.raises(InvalidCell):
        sync_once(desktop, session_root=session, owner_user=ACCOUNT, cursor=SyncCursor(),
                  post=calls.append)
    assert calls == []


def test_a_closed_session_cannot_sync():
    desktop, cloud = _device(), ReplicaCopy()
    _remember(desktop, "fact-rate", "site rate 450", 10)
    move_to(desktop, S_FOUNDER, ACTIVE)
    move_to(desktop, S_FOUNDER, CLOSED)
    with pytest.raises(InvalidCell):
        _sync(desktop, cloud)
    assert cloud.dump() == []


def test_a_server_answer_without_merged_fragments_writes_nothing():
    desktop = _device()
    _remember(desktop, "fact-rate", "site rate 450", 10)
    revision = desktop.snapshot().revision
    with pytest.raises(InvalidCell):
        sync_once(desktop, session_root=S_FOUNDER, owner_user=ACCOUNT, cursor=SyncCursor(),
                  post=lambda payload: {"new_hlc": "0", "merged": {}})
    assert desktop.snapshot().revision == revision
