"""The 300 s sync cycle, held to what it may cost and what it may claim.

Two defects lived here together on 2026-09-07, and they were the same
defect wearing two faces:

  * stamp_with_hlc ticked EVERY item on EVERY cycle. merge_snapshots
    resolves an id collision by "newer HLC wins", so the winner became
    whichever device synced most recently -- a device could silently
    revert another device's real edit with its own untouched copy.
  * Because no two cycles agreed, the whole corpus was re-serialised and
    rewritten every cycle: 176 MB on the founder machine, four live copies
    of the corpus in RAM, and 648 MB of embedding vectors lifted out of
    SQLite by SELECT * only to be dropped one line later.
"""
from __future__ import annotations

import json

from personal_brain import hlc, sync
from personal_brain.sync_worker import _synced_fragment_columns


def test_an_untouched_item_keeps_the_stamp_it_earned():
    """The HLC dates the edit. Syncing is not an edit."""
    hlc.reset_device_clock()
    item = {"id": "x", "text": "hello"}

    sync.stamp_with_hlc(item)
    first = item["provenance"]["hlc"]
    for _ in range(5):
        sync.stamp_with_hlc(item)

    assert item["provenance"]["hlc"] == first


def test_an_edited_item_advances():
    hlc.reset_device_clock()
    item = {"id": "x", "text": "hello"}
    sync.stamp_with_hlc(item)
    first = item["provenance"]["hlc"]

    item["text"] = "hello, changed"
    sync.stamp_with_hlc(item)

    assert item["provenance"]["hlc"] > first


def test_the_device_that_synced_last_does_not_beat_the_device_that_edited():
    """The law the bumping broke, stated as the merge sees it.

    Device A holds a record it has not touched since it was written.
    Device B edits that record afterwards. A then runs a sync cycle. A
    must not win: it has nothing newer to offer, only a newer sync.
    """
    hlc.reset_device_clock()
    on_a = {"id": "shared", "text": "the original"}
    sync.stamp_with_hlc(on_a)

    on_b = {"id": "shared", "text": "the edit B actually made"}
    sync.stamp_with_hlc(on_b)

    # A's cycle re-stamps everything it is about to push.
    sync.stamp_with_hlc(on_a)

    merged, _ = sync.merge_snapshots(
        {"fragments": [on_a], "skills": []},
        {"fragments": [on_b], "skills": []},
    )

    assert merged["fragments"][0]["text"] == "the edit B actually made"


def test_an_idle_corpus_pushes_the_same_bytes_twice(tmp_path):
    """No change means no new snapshot -- the shortcut this makes possible."""
    hlc.reset_device_clock()
    corpus = [
        {"id": "a", "text": "one"},
        {"id": "b", "text": "two"},
    ]
    path = tmp_path / "snapshot.json"
    transport = sync.JsonFileTransport(path)

    for item in corpus:
        sync.stamp_with_hlc(item)
    transport.push({"fragments": corpus, "skills": []})
    first = path.read_bytes()

    for item in corpus:
        sync.stamp_with_hlc(item)
    transport.push({"fragments": corpus, "skills": []})

    assert path.read_bytes() == first


def test_a_changed_corpus_does_not(tmp_path):
    """The shortcut must never hide a real edit."""
    hlc.reset_device_clock()
    corpus = [{"id": "a", "text": "one"}]
    path = tmp_path / "snapshot.json"
    transport = sync.JsonFileTransport(path)

    sync.stamp_with_hlc(corpus[0])
    transport.push({"fragments": corpus, "skills": []})
    first = path.read_bytes()

    corpus[0]["text"] = "one, edited"
    sync.stamp_with_hlc(corpus[0])
    transport.push({"fragments": corpus, "skills": []})

    assert path.read_bytes() != first


def test_the_cycle_never_reads_the_embeddings_it_throws_away(tmp_path):
    """648 MB of vectors, read out of SQLite and dropped, every 300 s."""
    import sqlite3

    conn = sqlite3.connect(str(tmp_path / "probe.sqlite3"))
    try:
        conn.execute(
            "CREATE TABLE fragments (id TEXT, text TEXT, scope TEXT,"
            " owner_user TEXT, embedding_blob BLOB)"
        )
        columns = _synced_fragment_columns(conn)
    finally:
        conn.close()

    assert "embedding_blob" not in columns
    assert '"text"' in columns
    assert '"id"' in columns


def test_provenance_that_arrived_as_json_text_is_still_honoured():
    """The store hands provenance over as a JSON string, not a dict."""
    hlc.reset_device_clock()
    item = {"id": "x", "text": "hello"}
    sync.stamp_with_hlc(item)
    stamped = item["provenance"]["hlc"]

    revived = {"id": "x", "text": "hello", "provenance": json.dumps(item["provenance"])}
    sync.stamp_with_hlc(revived)

    assert revived["provenance"]["hlc"] == stamped
