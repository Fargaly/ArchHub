"""Workshop task truth: short task names with live state, queue settlement apart from delivery,
Pause/Continue shown as requests until the owner answers. In-memory doubles, no app server."""
import copy
import sqlite3
from contextlib import contextmanager
import json

import pytest

from nodelang import workshop_api, workshop_mailbox, workshop_tasks
from nodelang.universal_cell import InvalidCell


class History:
    def __init__(self):
        self._db = sqlite3.connect(":memory:")

    @contextmanager
    def _transaction(self, write=False):
        with self._db:
            yield


def test_short_title_drops_jargon_and_keeps_one_clause():
    raw = ("WSFIX: Fix Workshop task titles in workshop_tasks.py (WSTASK-2) revision1302 desktopBridge=true; "
           "then queue settlement, steer truth and 5 more lines of detail")
    assert workshop_tasks.short_title(raw) == "Fix Workshop task titles"
    assert len(workshop_tasks.short_title("word " * 40)) <= 60
    assert workshop_tasks.short_title("Review the tower B drawings") == "Review the tower B drawings"


def test_column_state_follows_the_live_declaration(monkeypatch):
    monkeypatch.setattr(workshop_mailbox, "_session_alive", lambda row: row.get("alive", True))
    history = History()
    text = "Repair the release path: rebuild 03.TOOLS/x and publish revision1302"
    workshop_tasks.declared(history, "room:declaration:a", "req-1", text, "working", "key-a", "Claude")
    workshop_tasks.declared(history, "room:declaration:b", "req-2", "Draft the brief", "working", "key-b", "Codex")
    history._db.execute("CREATE TABLE workshop_declarations(root TEXT PRIMARY KEY, record TEXT)")
    def declare(root, request, status):
        history._db.execute("INSERT OR REPLACE INTO workshop_declarations VALUES(?,?)", (root, json.dumps(
            {"root":root, "request_id":request, "status":status, "agent":"x"})))
    declare("room:declaration:a", "req-1", "working")
    declare("room:declaration:b", "req-2", "blocked")
    history._db.execute("UPDATE workshop_tasks SET lease_until=0")  # both leases lapsed while still declared
    rows = {row["description"]: row for row in workshop_tasks.column(history)}
    assert rows[text]["title"] == "Repair the release path"
    assert rows[text]["status"] == "WIP" and rows[text]["owner"] == "Claude"
    assert rows["Draft the brief"]["status"] == "IN REVIEW"
    history._db.execute("DELETE FROM workshop_declarations")
    rows = {row["description"]: row for row in workshop_tasks.column(history)}
    assert rows[text]["status"] == "PLANNED" and rows[text]["owner"] is None
    workshop_tasks.declared(history, "room:declaration:a", "req-1", text, "done", "key-a", "Claude")
    assert {row["description"]: row for row in workshop_tasks.column(history)}[text]["status"] == "DONE"


class Api:
    """The WorkshopAPI methods under test over in-memory doubles of Work, store, route and relay records."""
    settleQueuedMessage = workshop_api.WorkshopAPI.settleQueuedMessage
    steerTask = workshop_api.WorkshopAPI.steerTask
    queueTaskMessage = workshop_api.WorkshopAPI.queueTaskMessage

    def __init__(self, outcome):
        self.saved, self.appended, self.routes, self.states = {"reviews":[], "queuedMessages":[]}, {}, [], {}
        self.outcome, self.request_id = outcome, "q1"

    def _work(self, task):
        return task

    def _options(self, task):
        return copy.deepcopy(self.saved)

    def _save(self, task, options):
        self.saved = copy.deepcopy(options)

    def _append(self, task, text, *, key, reply_to=None):
        return self.appended.setdefault(key, {"id":"msg-" + str(len(self.appended) + 1), "text":text})

    def _route(self, task, message):
        self.routes.append(message["id"])
        self.saved.update(delivery=dict(self.outcome), dispatch_message=message["id"])

    def _task(self, task):
        options = self._options(task)
        return {"queuedMessages":workshop_api._queued_rows(options, self.states),
                "control":workshop_api._control(options, self.states)}


def queued(api):
    return api.queueTaskMessage("t", "Pending instruction")["id"]


def test_not_sent_retries_the_same_stored_message():
    api = Api({"state":"not_sent", "reason":"recipient_not_exactly_one_live_session"})
    key = queued(api)
    first = api.settleQueuedMessage("t", key, True)
    assert first["state"] == "stored" and first["delivery"]["state"] == "not_sent"
    assert first["delivery"]["reason"] == "recipient_not_exactly_one_live_session"
    api.outcome = {"state":"started"}
    second = api.settleQueuedMessage("t", key, True)
    assert api.routes == ["msg-1", "msg-1"] and len(api.appended) == 1
    assert second["messageId"] == "msg-1" and second["delivery"]["state"] == "started"


def test_uncertain_and_started_never_replay():
    for outcome in ({"state":"uncertain", "reason":"dispatched without a recorded outcome"}, {"state":"started"}):
        api = Api(outcome)
        key = queued(api)
        api.settleQueuedMessage("t", key, True)
        again = api.settleQueuedMessage("t", key, True)
        assert api.routes == ["msg-1"] and again["delivery"]["state"] == outcome["state"]


def test_durable_unavailable_retries_and_replied_is_not_duplicated():
    api = Api({"state":"started"})
    key = queued(api)
    api.settleQueuedMessage("t", key, True)
    api.states["msg-1"] = {"state":"unavailable", "reason":"no live door"}
    api.settleQueuedMessage("t", key, True)
    assert api.routes == ["msg-1", "msg-1"]
    api.states["msg-1"] = {"state":"replied"}
    assert api.settleQueuedMessage("t", key, True)["delivery"]["state"] == "replied"
    assert api.routes == ["msg-1", "msg-1"]
    assert api._task("t")["queuedMessages"] == []


def test_withdraw_is_unchanged():
    api = Api({"state":"started"})
    key = queued(api)
    assert api.settleQueuedMessage("t", key, False)["state"] == "withdrawn"
    assert api.settleQueuedMessage("t", key, False)["state"] == "withdrawn"
    with pytest.raises(InvalidCell):
        api.settleQueuedMessage("t", key, True)
    assert api.routes == [] and api._task("t")["queuedMessages"] == []
    sent = Api({"state":"started"})
    key = queued(sent)
    sent.settleQueuedMessage("t", key, True)
    with pytest.raises(InvalidCell):
        sent.settleQueuedMessage("t", key, False)


def test_pause_is_requested_until_the_owner_replies():
    api = Api({"state":"started"})
    api.steerTask("t", "Pause")
    assert api._task("t")["control"] == {"request":"Pause", "state":"requested", "reason":None}
    api.states["msg-1"] = {"state":"replied"}
    assert api._task("t")["control"]["state"] == "acknowledged"
    blocked = Api({"state":"not_sent", "reason":"no_available_native_agent"})
    blocked.steerTask("t", "Continue")
    assert blocked._task("t")["control"] == {"request":"Continue", "state":"not_sent",
                                             "reason":"no_available_native_agent"}
    plain = Api({"state":"started"})
    plain.steerTask("t", "Keep the fire rating")
    assert plain._task("t")["control"] is None
