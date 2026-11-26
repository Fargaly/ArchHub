"""Founder 2026-11-25: 'I want it faster'. The installed launcher (e24eeb4) still spent 77% of a core idle: every
archived declaration rebuilt on each tick, Work column and room listing; every skill and schedule .archhub file
re-read and re-validated on each call; the waiting-mail query walked the whole room. Outputs must stay identical
to the uncached reads; only the repeated work goes."""
import json
import os
import sqlite3
import time
from types import SimpleNamespace

from nodelang import agent_declarations as ad
from nodelang import session_files as sf
from nodelang import workshop_api as api
from nodelang import workshop_mailbox as mb
from nodelang import workshop_tasks as wt

from test_launcher_tick_cost import _fill, _message, _record, _timed


def _best(call, runs=5):
    return min(_timed(call) for _ in range(runs))


def _fresh(monkeypatch):
    monkeypatch.setattr(ad, "_VERDICTS", {})
    monkeypatch.setattr(mb, "_BUILT", {})
    monkeypatch.setattr(mb, "_SHARED", (None, None, None))


def test_shared_archived_read_identical_unchanged_by_callers_and_sees_other_writers(monkeypatch):
    _fresh(monkeypatch)
    with mb.application_history() as history:
        _fill(history)
        db = history._db
        mb._records(db)   # no marker yet on a bare fixture table: install it as the app's store has it
        with history._transaction(write=True):
            for statement in mb.DECLARATIONS_MARKER_SCHEMA:
                db.execute(statement)
        plain = json.dumps(mb.read_declarations(db, include_archived=True))
        first = mb.read_declarations(db, include_archived=True, shared=True)
        assert json.dumps(first) == plain
        second = mb.read_declarations(db, include_archived=True, shared=True)
        assert second is not first and all(a is b for a, b in zip(first, second))   # same rows, new list

        # Every shared reader runs over the shared rows; none of them changes a row.
        with history._transaction(write=True):
            for i in range(200):
                message = _message(i, generic=False)
                stored = history.append(mb.ROOM, author=message["author"], content=message["content"],
                                        category=mb.CATEGORY, idempotency_key="idle-%d" % i)
                db.execute("CREATE TABLE IF NOT EXISTS workshop_waiting(message_id TEXT PRIMARY KEY, target TEXT NOT NULL)")
                db.execute("INSERT INTO workshop_waiting VALUES(?,?)", (stored["id"], "x"))
        worker = mb.WorkshopInjection(None, None)
        worker._progress, worker._watched_at = True, time.time()
        worker._tick(history, time.time())
        wt.column(history)
        wt.maintain_tasks(history)
        listing = api.WorkshopAPI(None, SimpleNamespace(subject_root="agent:session:%064x" % 1), None, None,
                                  guard=None, request_id=None, route=None).listWorkshopMessages()
        assert listing["messages"]
        assert json.dumps(mb._SHARED[2]) == json.dumps(mb.read_declarations(db, include_archived=True))

        before = _best(lambda: mb.read_declarations(db, include_archived=True))
        after = _best(lambda: mb.read_declarations(db, include_archived=True, shared=True))

        # A declaration written from a second connection (another process) is seen by the next shared read.
        other = sqlite3.connect(str(mb.profile_database()), isolation_level=None)
        try:
            changed = {**_record(5, live=False), "status": "blocked", "title": "from another writer"}
            other.execute("UPDATE workshop_declarations SET record=? WHERE root=?", (json.dumps(changed), changed["root"]))
        finally:
            other.close()
        seen = mb.read_declarations(db, include_archived=True, shared=True)
        assert next(row for row in seen if row["root"] == changed["root"])["title"] == "from another writer"
        assert json.dumps(seen) == json.dumps(mb.read_declarations(db, include_archived=True))
    print("\narchived read, 6000 declarations, unchanged table: before %.1f ms, after %.2f ms" % (before, after))
    assert after * 5 < before


def _old_message_identity(author, declared, subject_root):
    row = next((item for item in declared if author.endswith(" [" + item["session"] + "]")), None)
    if row is None:
        return {"who": "You" if author == subject_root else author, "author": author,
                "sender_key": author, "viewer_key": subject_root}
    return {"who": row.get("display_name") or api.LABELS.get(row["app"], row["agent"].split(" / ", 1)[0]),
            "model": row.get("model"), "provider": row["app"], "author": author,
            "sender_key": row["session"], "viewer_key": subject_root}


def test_message_identity_identical_and_cheaper():
    declared = [_record(i, live=False) for i in range(6000)]
    declared.append({**_record(6000, live=False), "session": "x] [agent:session:%064x" % 3})   # nested " ["
    declared.append({**_record(6001, live=False), "session": ""})
    authors = (["Sender [agent:session:%064x]" % (i * 37 % 6100) for i in range(100)]
               + ["a [x] [agent:session:%064x]" % 3, "a []", "nobody", "You", "b [agent:session:%064x" % 4, "[]", " []"])
    for author in authors:
        assert api._message_identity(author, declared, "You") == _old_message_identity(author, declared, "You"), author
    before = _best(lambda: [_old_message_identity(a, declared, "You") for a in authors], 3)
    def listing():
        first = api._first_by_session(declared)
        return [api._message_identity(a, declared, "You", first) for a in authors]
    after = _best(listing, 3)
    print("\nroom listing identities, 107 notes x 6002 declarations: before %.1f ms, after %.2f ms" % (before, after))
    assert after < before


def _document(count, title="Skill"):
    nodes = [{"id": "n%d" % i, "type": "param.value", "params": {"type": "number", "value": i},
              "position": {"x": i, "y": 0}, "pure": False} for i in range(count)]
    return {"format": "archhub", "version": 1, "id": "doc-1", "title": title, "nodes": nodes,
            "wires": [{"id": "w%d" % i, "from": {"node": "n%d" % i, "socket": "value"},
                       "to": {"node": "n%d" % (i + 1), "socket": "value"}} for i in range(count - 1)],
            "groups": [], "notes": [], "viewport": {"x": 0, "y": 0, "zoom": 1}}


def _uncached(path):
    held = dict(sf._DOCUMENTS)
    sf._DOCUMENTS.clear()
    try:
        return sf.read_document(path)
    finally:
        sf._DOCUMENTS.clear()
        sf._DOCUMENTS.update(held)


def test_document_read_cached_detached_and_reread_on_change(tmp_path, monkeypatch):
    monkeypatch.setattr(sf, "_DOCUMENTS", {})
    path = tmp_path / "skill.archhub"
    path.write_text(json.dumps(_document(2000)), encoding="utf-8")
    old = time.time() - 60
    os.utime(path, (old, old))
    expected = _uncached(path)
    first = sf.read_document(path)
    assert first == expected and str(path.resolve()) in sf._DOCUMENTS
    first["nodes"][0]["params"]["value"] = "changed by a caller"
    first["title"] = "changed"
    assert sf.read_document(path) == expected   # a caller's change never reaches the next read
    assert json.dumps(sf.read_document(path)) == json.dumps(_uncached(path))

    before = _best(lambda: _uncached(path))
    after = _best(lambda: sf.read_document(path))

    # Same size, new mtime: read again.
    path.write_text(json.dumps(_document(2000, title="Skilm")), encoding="utf-8")
    os.utime(path, (old + 1, old + 1))
    assert sf.read_document(path)["title"] == "Skilm"
    # A just-written file is never kept (one timestamp tick could hide a second same-size write).
    path.write_text(json.dumps(_document(2000, title="Skiln")), encoding="utf-8")
    assert sf.read_document(path)["title"] == "Skiln"
    path.write_text(json.dumps(_document(2000, title="Skilo")), encoding="utf-8")
    assert sf.read_document(path)["title"] == "Skilo"
    # An invalid file still fails on every read.
    path.write_text("{}", encoding="utf-8")
    os.utime(path, (old + 2, old + 2))
    for _ in range(2):
        try:
            sf.read_document(path)
            raise AssertionError("invalid document read")
        except ValueError:
            pass
    print("\n.archhub read, 2000 nodes, unchanged file: before %.1f ms, after %.1f ms" % (before, after))
    assert after * 2 < before


def test_waiting_query_identical_and_cheaper():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute("CREATE TABLE messages(id TEXT NOT NULL, conversation_id TEXT NOT NULL, sequence INTEGER NOT NULL, "
               "content TEXT NOT NULL, UNIQUE(conversation_id,id), UNIQUE(conversation_id,sequence))")
    db.execute("CREATE TABLE workshop_waiting(message_id TEXT PRIMARY KEY, target TEXT NOT NULL)")
    db.executemany("INSERT INTO messages VALUES(?,?,?,?)",
                   [("m%06d" % (i * 7919 % 30000), mb.ROOM if i % 50 else "other", i, "x") for i in range(30000)])
    old = ("SELECT m.* FROM messages m JOIN workshop_waiting w ON m.id=w.message_id "
           "WHERE m.conversation_id=? ORDER BY m.sequence LIMIT 2000")
    new = ("SELECT m.* FROM workshop_waiting w CROSS JOIN messages m ON m.id=w.message_id "
           "WHERE m.conversation_id=? ORDER BY m.sequence LIMIT 2000")
    assert new in open(mb.__file__, encoding="utf-8").read().replace('"\n                "', "")
    timings = {}
    for waiting in (543, 2600):   # 2600 waiting: the LIMIT cuts the same rows
        db.execute("DELETE FROM workshop_waiting")
        db.executemany("INSERT INTO workshop_waiting VALUES(?,?)",
                       [("m%06d" % (i * 11 % 30000), "x") for i in range(waiting)] + [("missing", "x")])
        assert [tuple(r) for r in db.execute(new, (mb.ROOM,))] == [tuple(r) for r in db.execute(old, (mb.ROOM,))]
        timings[waiting] = (_best(lambda: db.execute(old, (mb.ROOM,)).fetchall()),
                            _best(lambda: db.execute(new, (mb.ROOM,)).fetchall()))
    assert len(db.execute(new, (mb.ROOM,)).fetchall()) == 2000
    print("\nwaiting query, 30000 messages: 543 waiting before %.1f ms, after %.1f ms; 2600 waiting before %.1f ms, "
          "after %.1f ms" % (*timings[543], *timings[2600]))
    assert timings[543][1] < timings[543][0]
