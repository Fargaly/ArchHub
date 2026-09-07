"""The Brain bounds what it writes, so it cannot fill the founder's disk.

His disk reached 0.00 GB free, which took the Brain down and with it every
governance hook. Two leaks, both in the Brain's own storage (2026-09-07):

  * brain.db-wal had grown to 19 GB beside a 1 GB database, because nothing
    ever checkpointed it.
  * 80 abandoned brain-sync-snapshot .tmp files, 150 MB each, 6.18 GB --
    every failed snapshot write left its half-file behind, and once the disk
    was full every write failed, so the leak fed the condition causing it.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(
    Path(__file__).resolve().parents[1] / "personal-brain-mcp" / "src"
))
from personal_brain.sync import JsonFileTransport  # noqa: E402

STORAGE = (
    Path(__file__).resolve().parents[1] / "personal-brain-mcp" / "src"
    / "personal_brain" / "storage.py"
).read_text(encoding="utf-8")


def test_the_write_ahead_log_has_a_ceiling():
    assert "PRAGMA wal_autocheckpoint" in STORAGE
    assert "PRAGMA journal_size_limit" in STORAGE
    where = STORAGE.index("PRAGMA journal_mode=WAL")
    assert STORAGE.index("PRAGMA journal_size_limit") > where, (
        "the limit is set on the same connection that opens WAL"
    )


def test_a_snapshot_write_leaves_nothing_behind(tmp_path):
    target = tmp_path / "brain-sync-snapshot.json"
    JsonFileTransport(target).push({"fragments": [{"text": "one"}]})
    assert json.loads(target.read_text(encoding="utf-8"))["fragments"]
    assert list(tmp_path.glob("*.tmp")) == []


def test_a_write_that_fails_takes_its_half_file_with_it(tmp_path, monkeypatch):
    target = tmp_path / "brain-sync-snapshot.json"

    def explode(*args, **kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(json, "dump", explode)
    with pytest.raises(OSError):
        JsonFileTransport(target).push({"fragments": []})
    assert list(tmp_path.glob("*.tmp")) == [], (
        "a failed write must not leave a 150 MB orphan behind"
    )


def test_an_abandoned_snapshot_from_a_killed_process_is_swept(tmp_path):
    target = tmp_path / "brain-sync-snapshot.json"
    orphan = tmp_path / "brain-sync-snapshot.json.abcd1234.tmp"
    orphan.write_text("half a file", encoding="utf-8")
    old = time.time() - 3600
    os.utime(orphan, (old, old))

    JsonFileTransport(target).push({"fragments": []})
    assert not orphan.exists(), "a killed process cannot clean up after itself"


def test_a_snapshot_being_written_right_now_is_left_alone(tmp_path):
    """Sweeping must never take another process's live temp file."""
    target = tmp_path / "brain-sync-snapshot.json"
    live = tmp_path / "brain-sync-snapshot.json.zzzz9999.tmp"
    live.write_text("in flight", encoding="utf-8")

    JsonFileTransport(target).push({"fragments": []})
    assert live.exists()
