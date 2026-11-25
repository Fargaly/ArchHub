"""Founder 2026-11-25: 'the app and agents interaction is very slow'. The installed launcher spent over a core in
read_declarations: 6008 rows (5743 of dead processes) re-parsed and rebuilt on every poll and every commit.
The output must stay identical to the old algorithm; only unchanged rows stop being re-parsed."""
import json
import os
import time

import psutil

from nodelang import agent_declarations as ad
from nodelang import workshop_mailbox as mb


def _old_alive(row):
    # The pre-change _alive, verbatim apart from strict (never used by read_declarations).
    import psutil as _psutil
    import time as _time
    key = (row["pid"], row["created_at"])
    known = ad._VERDICTS.get(key)
    from nodelang.library_engines import LIBRARY_ITEM_ENGINES
    recheck = LIBRARY_ITEM_ENGINES['tool_workshop']['params']['session_poll_ms'] / 1000
    if known is not None and (known[0] is False or _time.monotonic() - known[1] < recheck):
        return known[0]
    return ad._alive(row)


def _old_session_alive(row):
    if _old_alive(row):
        return True
    if not row.get("native_session_id"):
        return False
    native = row.get("native_process")
    return bool(native and native["runtime"] == row["runtime"] and _old_alive(native))


def _old_read_declarations(connection, *, include_archived=False, records=None):
    """The pre-change read_declarations, verbatim (records: parsed rows)."""
    if not connection.execute("SELECT 1 FROM sqlite_master WHERE name='workshop_declarations'").fetchone():
        return []
    rows = ([json.loads(row[0]) for row in connection.execute("SELECT record FROM workshop_declarations ORDER BY root")]
            if records is None else [{**row, **({'aliases': list(row['aliases'])} if 'aliases' in row else {})} for row in records])
    for row in rows:
        row["sockets"] = {field: row["root"] + ":" + field for field in row if field not in ("sockets", "root")}
        row["process_alive"] = _old_session_alive(row)
        row["current"] = row["status"] != "done" and row["process_alive"]
    holders = {}
    for row in rows:
        if row.get("role") and row["current"] and (row["role"] not in holders
                or row.get("updated_at", "") > holders[row["role"]].get("updated_at", "")):
            holders[row["role"]] = row
    for row in rows:
        role = row.get("role")
        if not role:
            continue
        holder = holders.get(role)
        row["role_current"] = row is holder
        if holder is not None and not row["current"]:
            holder.setdefault("aliases", []).extend(alias for alias in mb._aliases({}, row)
                if not mb._exact_session_alias(alias, row))
    return [row for row in rows if include_archived or row["current"]]


def _record(index, live, *, done_every=23, role_every=50, lineage=8):
    me = psutil.Process()
    pid, created = (os.getpid(), me.create_time()) if live else (900001 + index * 4 + 1, 1.5 + index)
    return {"root": "room:declaration:%064x" % index, "agent": "Claude Code / proj / session-%012x" % index,
            "session": "agent:session:%064x" % index, "task": "task " * 20, "request_id": "req-%d" % index,
            "paths": ["c:/users/x/file%d" % j for j in range(3)],
            "status": "done" if index % done_every == 0 else "working", "project": "11.ARCHHUB-APP", "cwd": "c:/x",
            "runtime": "claude", "app": "claude", "native_session_id": "%032x" % index,
            "pid": pid, "created_at": created,
            "process_lineage": [{"pid": pid + j, "created_at": 2.0 + j} for j in range(lineage)],
            "native_process": {"runtime": "claude", "pid": 950001 + index * 4 + 1, "created_at": 3.0},
            "version": 3, "updated_at": "2026-11-%02dT00:00:00+00:00" % (1 + index % 25),
            **({"role": "builder:x", "display_name": "Builder %d" % index, "aliases": ["b%d" % index]}
               if index % role_every == 0 else {})}


def _fill(history, *, count=6000, live_every=1000):
    with history._transaction(write=True):
        history._db.execute("CREATE TABLE IF NOT EXISTS workshop_declarations("
                            "root TEXT PRIMARY KEY,record TEXT NOT NULL CHECK(json_valid(record))) STRICT")
        history._db.execute("CREATE TABLE IF NOT EXISTS bench_tick(n INTEGER)")
        history._db.executemany("INSERT INTO workshop_declarations VALUES(?,?)", [
            ("room:declaration:%064x" % i, json.dumps(_record(i, live=i % live_every == 1))) for i in range(count)])


def _ms(call, *, repeat=5, between=lambda: None):
    total = 0.0
    for _ in range(repeat):
        between()
        start = time.perf_counter()
        call()
        total += time.perf_counter() - start
    return total / repeat * 1000


def test_declarations_identical_to_old_algorithm_and_cheaper(monkeypatch):
    monkeypatch.setattr(ad, "_VERDICTS", {})
    monkeypatch.setattr(mb, "_BUILT", {})
    with mb.application_history() as history:
        _fill(history)
        db = history._db
        old, new = (_old_read_declarations(db, include_archived=True),
                    mb.read_declarations(db, include_archived=True))
        assert len(new) == 6000 and sum(row["current"] for row in new) > 0
        assert json.dumps(new) == json.dumps(old)   # same rows, fields, values and key order
        assert json.dumps(mb.read_declarations(db)) == json.dumps(_old_read_declarations(db))
        # A caller changing its rows never changes the next read.
        for row in new:
            row["sockets"]["x"] = "y"
            row.setdefault("aliases", []).append("changed")
            row["status"] = "changed"
        assert json.dumps(mb.read_declarations(db, include_archived=True)) == json.dumps(old)

        before = _ms(lambda: _old_read_declarations(db, include_archived=True))
        after = _ms(lambda: mb.read_declarations(db, include_archived=True))

        watch = mb.store_watch(timeout_seconds=2)
        try:
            def tick():   # another writer commits (every Workshop message does), so each poll sees a new version
                with history._transaction(write=True):
                    history._db.execute("INSERT INTO bench_tick VALUES (1)")

            def old_watch():   # the old _parsed (json.loads of every record per commit) + old read_declarations
                parsed = [json.loads(row[0]) for row in watch._db.execute(
                    "SELECT record FROM workshop_declarations ORDER BY root")]
                return _old_read_declarations(watch._db, include_archived=True, records=parsed)

            assert json.dumps(watch.declarations(include_archived=True)) == json.dumps(old_watch())
            watch_before = _ms(old_watch, between=tick)
            watch_after = _ms(lambda: watch.declarations(include_archived=True), between=tick)
        finally:
            watch.close()
    print("\nread_declarations(include_archived=True) 6000 rows: before %.1f ms, after %.1f ms" % (before, after))
    print("_StoreWatch.declarations per commit 6000 rows: before %.1f ms, after %.1f ms" % (watch_before, watch_after))
    assert after < before and watch_after < watch_before
