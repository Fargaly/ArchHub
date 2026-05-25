"""Slice 6 — sync layer tests (HLC + Transport + merge)."""
from __future__ import annotations

import json
import time

import pytest

from personal_brain import hlc, sync


# ─────────────────────── HLC ───────────────────────────────────────────


def test_hlc_tick_monotonic():
    h = hlc.HLC.now()
    ts1 = h.tick()
    ts2 = h.tick()
    ts3 = h.tick()
    assert ts1 < ts2 < ts3


def test_hlc_receive_advances_on_remote_ahead():
    h = hlc.HLC(phys_ms=1000, logical=0)
    remote = hlc.pack(2000, 0)
    new = h.receive(remote)
    p, l = hlc.unpack(new)
    assert p >= 2000


def test_hlc_receive_handles_tie_by_bumping_logical():
    # Use a phys_ms in the far future so wallclock can't move best_phys
    # past it during the test — otherwise best_phys = real_now_ms > self.phys_ms
    # and the tie case never triggers.
    future_ms = int(time.time() * 1000) + 10_000_000_000  # ~3 months out
    h = hlc.HLC(phys_ms=future_ms, logical=0)
    remote = hlc.pack(future_ms, 0)
    new = h.receive(remote)
    _, l = hlc.unpack(new)
    assert l >= 1


def test_hlc_pack_unpack_roundtrip():
    for (p, l) in [(0, 0), (1, 0), (1000, 5), (1 << 40, 0xfff)]:
        packed = hlc.pack(p, l)
        rp, rl = hlc.unpack(packed)
        assert (rp, rl) == (p, l)


def test_hlc_compare():
    assert hlc.compare(1, 2) == -1
    assert hlc.compare(2, 1) == 1
    assert hlc.compare(5, 5) == 0


def test_device_clock_singleton():
    hlc.reset_device_clock()
    c1 = hlc.device_clock()
    c2 = hlc.device_clock()
    assert c1 is c2


# ─────────────────────── JSON file transport ───────────────────────────


def test_json_file_transport_roundtrip(tmp_path):
    t = sync.JsonFileTransport(tmp_path / "snap.json")
    snap = {"version": 1, "fragments": [{"id": "x", "text": "hello"}]}
    t.push(snap)
    fetched = t.pull()
    assert fetched == snap


def test_json_file_transport_pull_empty_returns_none(tmp_path):
    t = sync.JsonFileTransport(tmp_path / "no-such.json")
    assert t.pull() is None


def test_json_file_transport_atomic_write(tmp_path):
    """Verify atomic write — no leftover tmp file after success."""
    path = tmp_path / "snap.json"
    t = sync.JsonFileTransport(path)
    t.push({"a": 1})
    tmps = list(tmp_path.glob("snap.json.*.tmp"))
    assert tmps == []


def test_json_file_transport_handles_malformed_file(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("not json {{{")
    t = sync.JsonFileTransport(path)
    assert t.pull() is None


# ─────────────────────── merge ─────────────────────────────────────────


def _frag(fid, text, hlc_ts=0, created_at=""):
    return {
        "id": fid, "text": text,
        "provenance": {"hlc": hlc_ts, "created_at": created_at},
    }


def test_merge_union_unique_items():
    a = {"fragments": [_frag("a", "A"), _frag("b", "B")]}
    b = {"fragments": [_frag("c", "C")]}
    merged, res = sync.merge_snapshots(a, b)
    ids = {f["id"] for f in merged["fragments"]}
    assert ids == {"a", "b", "c"}
    assert res.fragments == 3


def test_merge_collision_newer_hlc_wins():
    a = {"fragments": [_frag("x", "A-old", hlc_ts=100)]}
    b = {"fragments": [_frag("x", "B-new", hlc_ts=200)]}
    merged, _ = sync.merge_snapshots(a, b)
    x = next(f for f in merged["fragments"] if f["id"] == "x")
    assert x["text"] == "B-new"


def test_merge_collision_local_newer_wins():
    a = {"fragments": [_frag("x", "A-newer", hlc_ts=999)]}
    b = {"fragments": [_frag("x", "B-older", hlc_ts=50)]}
    merged, _ = sync.merge_snapshots(a, b)
    x = next(f for f in merged["fragments"] if f["id"] == "x")
    assert x["text"] == "A-newer"


def test_merge_commutative():
    a = {"fragments": [_frag("x", "A", hlc_ts=100), _frag("y", "Y", hlc_ts=10)]}
    b = {"fragments": [_frag("x", "B", hlc_ts=200), _frag("z", "Z", hlc_ts=10)]}
    m1, _ = sync.merge_snapshots(a, b)
    m2, _ = sync.merge_snapshots(b, a)
    # Compare sorted by id
    s1 = sorted(m1["fragments"], key=lambda x: x["id"])
    s2 = sorted(m2["fragments"], key=lambda x: x["id"])
    assert [f["text"] for f in s1] == [f["text"] for f in s2]


def test_merge_idempotent():
    a = {"fragments": [_frag("x", "A", hlc_ts=100)]}
    b = {"fragments": [_frag("x", "B", hlc_ts=200), _frag("y", "Y", hlc_ts=300)]}
    m1, _ = sync.merge_snapshots(a, b)
    m2, _ = sync.merge_snapshots(a, m1)
    s1 = sorted(m1["fragments"], key=lambda x: x["id"])
    s2 = sorted(m2["fragments"], key=lambda x: x["id"])
    assert [(f["id"], f["text"]) for f in s1] == [(f["id"], f["text"]) for f in s2]


def test_merge_falls_back_to_created_at_when_hlc_tied():
    a = {"fragments": [_frag("x", "A", hlc_ts=0, created_at="2026-05-01")]}
    b = {"fragments": [_frag("x", "B", hlc_ts=0, created_at="2026-05-20")]}
    merged, _ = sync.merge_snapshots(a, b)
    x = next(f for f in merged["fragments"] if f["id"] == "x")
    assert x["text"] == "B"  # newer created_at wins


def test_merge_handles_skills_too():
    a = {"skills": [{"id": "sk-1", "name": "alpha", "provenance": {"hlc": 100}}]}
    b = {"skills": [{"id": "sk-1", "name": "alpha-newer", "provenance": {"hlc": 200}},
                     {"id": "sk-2", "name": "beta",        "provenance": {"hlc": 10}}]}
    merged, res = sync.merge_snapshots(a, b)
    assert res.skills == 2
    s1 = next(s for s in merged["skills"] if s["id"] == "sk-1")
    assert s1["name"] == "alpha-newer"


# ─────────────────────── sync round-trip ───────────────────────────────


def test_sync_pulls_merges_pushes(tmp_path):
    path = tmp_path / "fleet.json"
    t = sync.JsonFileTransport(path)
    # Device A pushes
    a_snap = {"fragments": [_frag("a", "from-A", hlc_ts=10)]}
    t.push(a_snap)
    # Device B syncs with its own snapshot
    b_snap = {"fragments": [_frag("b", "from-B", hlc_ts=20)]}
    merged, res = sync.sync(b_snap, t)
    ids = {f["id"] for f in merged["fragments"]}
    assert ids == {"a", "b"}
    # The transport now has the merged snapshot
    after = t.pull()
    assert after is not None
    after_ids = {f["id"] for f in after["fragments"]}
    assert after_ids == {"a", "b"}


def test_stamp_with_hlc_attaches_timestamp():
    hlc.reset_device_clock()
    item = {"id": "x", "text": "hello"}
    sync.stamp_with_hlc(item)
    assert "provenance" in item
    assert isinstance(item["provenance"]["hlc"], int)
    assert item["provenance"]["hlc"] > 0


def test_stamp_with_hlc_advances_clock():
    hlc.reset_device_clock()
    a = {}
    b = {}
    sync.stamp_with_hlc(a)
    sync.stamp_with_hlc(b)
    assert b["provenance"]["hlc"] > a["provenance"]["hlc"]


# ─────────────────────── stub transports ──────────────────────────────


def test_loro_transport_init_with_real_loro(tmp_path):
    """With loro installed, init succeeds. Without loro, raises clear error."""
    try:
        t = sync.LoroTransport(tmp_path / "doc.loro")
        assert t.name == "loro-crdt"
    except RuntimeError as ex:
        assert "loro" in str(ex)


def test_speckle_spatial_transport_init_works(tmp_path):
    t = sync.SpeckleSpatialTransport(tmp_path / "speckle", stream_id="test-stream")
    assert t.name == "speckle-spatial"
    assert t.stream_id == "test-stream"
    assert t.store_path.exists()


def test_speckle_spatial_transport_push_pull(tmp_path):
    t = sync.SpeckleSpatialTransport(tmp_path / "speckle")
    snap = {
        "fragments": [
            {"id": "wall-1", "kind": "spatial", "text": "wall geom hash abc"},
            {"id": "fact-1", "kind": "fact", "text": "user prefers metric"},
        ],
        "snapshot_ms": 12345,
    }
    t.push(snap)
    got = t.pull()
    assert got is not None
    # Spatial fragment came back; non-spatial filtered out
    spatial_ids = {f.get("id") for f in got["fragments"]}
    assert "wall-1" in spatial_ids
    assert "fact-1" not in spatial_ids
    assert got["snapshot_ms"] == 12345


def test_loro_transport_real_roundtrip(tmp_path):
    t = sync.LoroTransport(tmp_path / "doc.loro")
    snap = {"fragments": [{"id": "a", "text": "x"}]}
    t.push(snap)
    got = t.pull()
    assert got == snap


def test_loro_transport_handles_empty_pull(tmp_path):
    t = sync.LoroTransport(tmp_path / "missing.loro")
    assert t.pull() is None


def test_loro_transport_cross_device_merge(tmp_path):
    """Two devices push to separate Loro files. Fragment-level union via
    merge_snapshots is the canonical merge; Loro's doc-level CRDT is the
    transport layer below it."""
    a = sync.LoroTransport(tmp_path / "a.loro")
    b = sync.LoroTransport(tmp_path / "b.loro")
    a.push({"fragments": [{"id": "a", "provenance": {"hlc": 10}}]})
    b.push({"fragments": [{"id": "b", "provenance": {"hlc": 20}}]})
    # Each device's pull returns its own snapshot
    snap_a = a.pull()
    snap_b = b.pull()
    assert {f["id"] for f in snap_a["fragments"]} == {"a"}
    assert {f["id"] for f in snap_b["fragments"]} == {"b"}
    # Application-level fragment union via merge_snapshots
    final, stats = sync.merge_snapshots(snap_a, snap_b)
    assert {f["id"] for f in final["fragments"]} == {"a", "b"}
    # And the raw byte export+import path works for transport-level sync
    remote_bytes = b.export_snapshot_bytes()
    assert remote_bytes is not None and len(remote_bytes) > 0
