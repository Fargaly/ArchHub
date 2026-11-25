"""Founder 2026-11-25: 'the app and agents interaction is very slow ... I want it faster'. The installed launcher
(d8a8281) still spent a core: the injection tick resolved every waiting message against every declaration, the Work
column re-scanned the whole room, and live-only reads rebuilt ~5700 rows of dead processes. Results must stay
identical to the old algorithms; only the repeated work goes."""
import json
import math
import os
import re
import time
from hashlib import sha256

import psutil

from nodelang import agent_declarations as ad
from nodelang import workshop_mailbox as mb
from nodelang import workshop_tasks as wt


# ---- the pre-change algorithms, verbatim (origin/main cd9af378) ----

def _old_recipient_rows(message, declarations):
    if not mb.agent_addressed(message):
        return []
    targets = [value.casefold() for value in mb._header_targets(message) if value.casefold() not in mb._ROOM_TARGETS]
    ambiguous = {target for target in targets if re.fullmatch(r"[0-9a-f]{3,}", target)
        and len({row.get("native_session_id") for row in declarations
            if str(row.get("native_session_id") or "").casefold().startswith(target)}) > 1}
    ambiguous = {target for target in ambiguous if not any(target in mb._aliases({}, row) for row in declarations)}
    ambiguous |= {target for target in targets if re.fullmatch(r"[0-9a-f]{12}", target) and len({mb.recipient_identity(row)
        for row in declarations if row.get("current") and target in mb._aliases({}, row)}) > 1}
    if ambiguous:
        message = {**message, "content":"To " + ", ".join(target for target in targets if target not in ambiguous)
            + ":\n" + message["content"].partition("\n")[2]}
    author = str(message.get("author") or "")
    matched = [row for row in declarations if row.get("current")
        and "[" + row["session"] + "]" not in author and mb._addressed(message,
        {"sender":row["agent"] + " [" + row["session"] + "]", "sender_label":row["agent"],
         "sender_key":row["session"]}, row)]
    project = mb._message_project(message)
    if not project:
        return matched
    kept = []
    for row in matched:
        identity = {"sender": row["agent"] + " [" + row["session"] + "]", "sender_label": row["agent"],
                    "sender_key": row["session"]}
        if str(row.get("project") or "") in ("", project) or mb._personally_addressed(message, identity, row):
            kept.append(row)
    return kept


def _old_resolve(history, message, declarations):
    rows = _old_recipient_rows(message, declarations)
    author, sessions = mb._replied_author(history, message), {row["session"] for row in rows}
    rows += [row for row in declarations if row.get("current") and row["session"] not in sessions
             and mb._reply_reaches(author, message, row)]
    newest = {}
    for row in sorted(rows, key=lambda row: str(row.get("updated_at") or "")):
        newest[mb.recipient_identity(row)] = row
    return [row for row in rows if any(row is kept for kept in newest.values())]


def _old_task_threads(history):
    bound, last = {}, {}
    for message, author, content, category, task, created in history._db.execute(
            "SELECT m.id, m.author, m.content, m.category, r.value, m.created_at FROM messages m, json_each(m.refs) r "
            "WHERE m.conversation_id=? AND json_valid(m.refs) ORDER BY m.sequence", (mb.ROOM,)):
        last[task] = content
        thread = bound.setdefault(task, [])
        if author != mb.DELIVERY_AUTHOR and category != mb.DELIVERY_CATEGORY and not (thread and thread[-1]["id"] == message):
            thread.append({"id": message, "who": author, "text": wt._without_header(content), "at": created})
    return bound, last


# ---- fixture: 6000 declarations (300 live), 2000 waiting messages ----

def _native(index):
    return sha256(b"native-%d" % index).hexdigest()[:32]


def _record(index, live):
    me = psutil.Process()
    pid, created = (os.getpid(), me.create_time()) if live else (900001 + index * 4 + 1, 1.5 + index)
    # Rows 1 and 21 share a session tag (F243); rows 41 and 61 are two rows of one native session.
    tag = "%012x" % (1 if index == 21 else index)
    native = _native(41 if index == 61 else index)
    role = {0: "717", 100: "717", 200: "research", 300: "design"}.get(index % 400 if index % 100 == 0 else -1)
    return {"root": "room:declaration:%064x" % index,
            "agent": ("Codex" if index % 3 else "Claude Code") + " / proj%d / session-%s" % (index % 4, tag),
            "session": "agent:session:%064x" % index, "task": "task", "request_id": "req-%d" % index,
            "paths": ["c:/x"], "status": "done" if index % 23 == 0 else "working",
            "project": ("11.ARCHHUB-APP", "OTHER", "")[index % 3], "cwd": "c:/x",
            "runtime": "codex" if index % 3 else "claude", "app": "claude", "native_session_id": native,
            "pid": pid, "created_at": created,
            "native_process": {"runtime": "claude", "pid": 950001 + index * 4 + 1, "created_at": 3.0},
            "version": 3, "updated_at": "2026-11-%02dT00:00:%02d+00:00" % (1 + index % 25, index % 60),
            **({"role": role} if role else {}),
            **({"display_name": "Builder %d" % index, "aliases": ["b%d" % index]} if index % 50 == 7 else {})}


def _targets(index, *, generic=True):
    live = 1 + 20 * (index % 300)
    dead = 2 + 20 * (index % 290)
    choices = [
        "Codex / proj%d / session-%012x" % (live % 4, live), "session-%012x" % dead, "%012x" % live, "%012x" % 1,
        _native(live)[:4], _native(dead)[:6], "717", "c91e", "coordinator", "design", "r&d", "Builder %d" % (7 + 50 * (index % 120)),
        "b%d" % (7 + 50 * (index % 120)), "everyone", "founder", "claude", "codex", "copilot", _native(41)[:12],
        "Claude Code / moved / session-%012x" % (3 * (index % 100)), "abc", "0",
    ]
    if not generic:   # a real note names one to three agents, never every session of an app
        choices = [value for value in choices if value not in mb._GENERIC_ALIASES and value not in mb._ROOM_TARGETS]
    picked = [choices[(index * 7 + step * 5) % len(choices)] for step in range(1 + index % 3)]
    return ", ".join(picked)


def _message(index, *, routing=None, generic=True):
    evidence = [mb.ROUTING_EVIDENCE, json.dumps(routing)] if routing is not None else []
    return {"id": "m%d" % index, "category": mb.CATEGORY, "author": "Sender [agent:session:%064x]" % (index % 7 * 20 + 1),
            "content": "To " + _targets(index, generic=generic) + ":\nPlease check %d?" % index, "evidence": evidence, "reply_to": None,
            "created_at": "2026-11-26T00:00:00+00:00"}


def _fill(history, *, count=6000, live_every=20):
    with history._transaction(write=True):
        history._db.execute("CREATE TABLE IF NOT EXISTS workshop_declarations("
                            "root TEXT PRIMARY KEY,record TEXT NOT NULL CHECK(json_valid(record))) STRICT")
        history._db.executemany("INSERT INTO workshop_declarations VALUES(?,?)", [
            ("room:declaration:%064x" % i, json.dumps(_record(i, live=i % live_every == 1 or i in (61,))))
            for i in range(count)])


def _roots(rows):
    return [row["root"] for row in rows]


def test_recipients_identical_to_old_algorithm_and_tick_cheaper(monkeypatch):
    monkeypatch.setattr(ad, "_VERDICTS", {})
    monkeypatch.setattr(mb, "_BUILT", {})
    with mb.application_history() as history:
        _fill(history)
        declarations = mb._Known(mb.read_declarations(history._db, include_archived=True))
        assert sum(row["current"] for row in declarations) >= 280
        messages = [_message(i) for i in range(2000)]
        messages += [_message(5000 + i, routing={"project": ("11.ARCHHUB-APP", "OTHER")[i % 2],
            "recipients": [{"session": "agent:session:%064x" % (1 + 20 * i)}] if i % 3 else None}) for i in range(300)]
        resolved = 0
        for message in messages:
            old = _old_resolve(history, message, declarations)
            assert _roots(mb._resolve(history, message, declarations)) == _roots(old), message["content"]
            assert _roots(mb._resolve(history, message, list(declarations))) == _roots(old)
            resolved += bool(old)
        assert resolved > 1000   # the fixture really addresses agents

        # (b) one injection pass over 2000 waiting messages, as _settle_waiting resolves them (per target).
        def settle_pass(resolve):
            known = mb._Known(mb.read_declarations(history._db, include_archived=True))
            for message in messages[:2000]:
                for target in [part for part in mb._header_targets(message) if part.casefold() not in mb._ROOM_TARGETS]:
                    resolve(history, {**message, "content": "To " + target + ":\nx"}, known)

        start = time.perf_counter()
        settle_pass(_old_resolve)
        before = (time.perf_counter() - start) * 1000
        after = math.inf
        for _ in range(3):
            start = time.perf_counter()
            settle_pass(mb._resolve)
            after = min(after, (time.perf_counter() - start) * 1000)
    print("\ninjection pass, 6000 declarations x 2000 waiting messages: before %.0f ms, after %.0f ms" % (before, after))
    assert after * 5 < before


def test_real_tick_over_waiting_messages_is_bounded(monkeypatch):
    monkeypatch.setattr(ad, "_VERDICTS", {})
    monkeypatch.setattr(mb, "_BUILT", {})
    with mb.application_history() as history:
        _fill(history)
        history._db.execute("CREATE TABLE IF NOT EXISTS workshop_waiting(message_id TEXT PRIMARY KEY, target TEXT NOT NULL)")
        with history._transaction(write=True):
            for i in range(2000):
                message = _message(i, generic=False)
                stored = history.append(mb.ROOM, author=message["author"], content=message["content"],
                                        category=mb.CATEGORY, idempotency_key="bench-%d" % i)
                history._db.execute("INSERT INTO workshop_waiting VALUES(?,?)", (stored["id"], "x"))
        worker = mb.WorkshopInjection(None, None)

        def tick(resolve, recipient_rows):
            monkeypatch.setattr(mb, "_resolve", resolve)
            monkeypatch.setattr(mb, "_recipient_rows", recipient_rows)
            worker._progress, worker._watched_at = True, time.time()
            start = time.perf_counter()
            worker._tick(history, time.time())
            return (time.perf_counter() - start) * 1000

        new_resolve, new_rows = mb._resolve, mb._recipient_rows
        tick(new_resolve, new_rows)   # first pass writes the addressed and attempt receipts
        before = tick(_old_resolve, _old_recipient_rows)
        after = min(tick(new_resolve, new_rows) for _ in range(3))
    print("\nsteady injection tick, 2000 waiting messages: before %.0f ms, after %.0f ms" % (before, after))
    assert after < before


def test_live_and_session_reads_identical_and_cheaper(monkeypatch):
    """BABOOM's reaction reader and the connectors' poll read live rows or one session's row; they rebuilt all 6000."""
    monkeypatch.setattr(ad, "_VERDICTS", {})
    monkeypatch.setattr(mb, "_BUILT", {})
    with mb.application_history() as history:
        _fill(history)
        db = history._db
        everything = mb.read_declarations(db, include_archived=True)
        assert json.dumps(mb.read_declarations(db)) == json.dumps([row for row in everything if row["current"]])
        for index in (0, 1, 2, 100, 61, 41, 5999):
            session = "agent:session:%064x" % index
            assert json.dumps(mb.read_declarations(db, include_archived=True, session=session)) == json.dumps(
                [row for row in everything if row["session"] == session])
        records = [row[0] for row in db.execute("SELECT record FROM workshop_declarations ORDER BY root")]

        def best(call):
            return min(_timed(call) for _ in range(5))
        before = best(lambda: [row for row in mb.read_declarations(db, include_archived=True, records=records)
                               if row["current"]])
        after = best(lambda: mb.read_declarations(db, records=records))
        one_before = best(lambda: next(row for row in mb.read_declarations(db, include_archived=True, records=records)
                                       if row["session"] == "agent:session:%064x" % 1))
        one_after = best(lambda: mb.read_declarations(db, include_archived=True, records=records,
                                                      session="agent:session:%064x" % 1))
    print("\nlive rows of 6000: before %.1f ms, after %.1f ms; one session: before %.1f ms, after %.1f ms"
          % (before, after, one_before, one_after))
    assert after < before and one_after < one_before


def _timed(call):
    start = time.perf_counter()
    call()
    return (time.perf_counter() - start) * 1000


def test_task_threads_cache_identical_and_invalidated(monkeypatch):
    monkeypatch.setattr(wt, "_THREADS", {})
    with mb.application_history() as history:
        with history._transaction(write=True):
            for i in range(3000):
                history.append(mb.ROOM, author="A%d [agent:session:x]" % (i % 5), content="To x:\nnote %d" % i,
                               category=mb.CATEGORY if i % 9 else mb.DELIVERY_CATEGORY,
                               refs=("task-%d" % (i % 40),) if i % 4 else (), idempotency_key="t-%d" % i)
        before = min(_timed(lambda: _old_task_threads(history)) for _ in range(3))
        assert wt._task_threads(history) == _old_task_threads(history)
        after = min(_timed(lambda: wt._task_threads(history)) for _ in range(3))
        assert wt._task_threads(history) == _old_task_threads(history)
        # A new message is seen (incremental) ...
        with history._transaction(write=True):
            added = history.append(mb.ROOM, author="B [agent:session:y]", content="To x:\nnew", category=mb.CATEGORY,
                                   refs=("task-1", "task-new"), idempotency_key="t-new")
        threads, last = wt._task_threads(history)
        assert (threads, last) == _old_task_threads(history)
        assert threads["task-new"][-1]["id"] == added["id"] and last["task-1"] == "To x:\nnew"
        # ... and a removed one rebuilds (retention deletes old notes).
        with history._transaction(write=True):
            first = history._db.execute("SELECT id FROM messages WHERE conversation_id=? AND refs!='[]' "
                                        "ORDER BY sequence LIMIT 1", (mb.ROOM,)).fetchone()[0]
            history._db.execute("DELETE FROM messages WHERE conversation_id=? AND id=?", (mb.ROOM, first))
        assert wt._task_threads(history) == _old_task_threads(history)
    print("\n_task_threads, 3000 notes, unchanged room: before %.1f ms, after %.2f ms" % (before, after))
    assert after < before
