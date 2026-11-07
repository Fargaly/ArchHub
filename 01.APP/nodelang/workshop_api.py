"""Design-named data functions over the existing Workshop Work and content owners.

No UI, provider simulation, task database or execution authority is introduced.
Task status is projected from committed Work state and live declarations.
"""



FUNCTIONS = frozenset({"listAgentsWorking", "listTasks", "listWorkshopMessages", "sendToBaboom", "setTaskStatus",
    "reassignTask", "setTaskDelegate", "queueTaskMessage", "settleQueuedMessage",
    "steerTask", "addTaskReview", "resolveTaskReview", "setTaskActivity"})
LABELS = {"claude":"Claude", "codex":"Codex", "antigravity":"Antigravity",
          "antigravity-ide":"Antigravity", "gemini":"Gemini", "opencode":"OpenCode",
          "goose":"Goose", "baboom":"BABOOM"}
STATES = {"open":"PLANNED", "claimed":"WIP", "blocked":"PLANNED",
          "review":"IN REVIEW", "complete":"DONE", "cancelled":"ARCHIVED"}
# Definitive non-dispatch: the same stored message may be routed again.
RETRYABLE_DELIVERY = frozenset({"not_sent", "unavailable"})


def _delivery_of(message_id, states, saved):
    """One stored message's delivery: its durable relay record, else what routing saved for it."""
    found = states.get(message_id)
    return found if found and found["state"] != "stored" else saved or {"state":"stored"}


def _queued_rows(options, states):
    """Queued notes still on the task: waiting ones, and stored ones until their owner replied."""
    shown = []
    for item in options.get("queuedMessages", []):
        if item["state"] == "withdrawn":
            continue
        if item["state"] != "queued":
            item = {**item, "delivery":_delivery_of(item.get("messageId"), states, item.get("delivery"))}
            if item["delivery"]["state"] == "replied":
                continue
        shown.append(item)
    return shown


def _control(options, states):
    """Pause/Continue is a request until the owner answers it; no native owner exposes execution control."""
    control = options.get("control")
    if not control:
        return None
    delivery = _delivery_of(control["messageId"], states, control.get("delivery"))
    state = ("acknowledged" if delivery["state"] == "replied" else
             "not_sent" if delivery["state"] in RETRYABLE_DELIVERY else "requested")
    return {"request":control["request"], "state":state, "reason":delivery.get("reason")}


def _message_identity(author, declared, subject_root):
    row = next((item for item in declared
                if author.endswith(" [" + item["session"] + "]")), None)
    if row is None:
        return {"who": "You" if author == subject_root else author, "author": author,
                "sender_key": author, "viewer_key": subject_root}
    return {"who": row.get("display_name") or LABELS.get(row["app"], row["agent"].split(" / ", 1)[0]),
            "model": row.get("model"), "provider": row["app"], "author": author,
            "sender_key": row["session"], "viewer_key": subject_root}


class WorkshopAPI:
    def __init__(self, owner, binding, root, scope, *, guard, request_id, route, message_limit=1000):
        self.owner, self.binding, self.root, self.scope = owner, binding, root, scope
        self.guard, self.request_id = guard, request_id
        self.message_limit = message_limit
        self.route = route
















































    def listTasks(self):
        # The Work column is the Workshop tasks table, the same rows the no-graph server shows.
        from .workshop_mailbox import application_history
        from .workshop_tasks import column
        with application_history() as history:
            return column(history)


    def listWorkshopMessages(self, before=None):
        """The existing public room, including notes that have no Work reference."""
        from .workshop_mailbox import CATEGORY, agent_addressed, delivery_events
        from .workshop_delivery_state import project_injection_delivery
        if before is not None and (type(before) is not int or before < 1):
            raise ValueError("Workshop message cursor is invalid")
        from .workshop_mailbox import application_history, read_declarations
        with application_history() as history:
            declared = read_declarations(history._db, include_archived=True)
            with history._transaction():
                rows, more = history._collect(history._db.execute("SELECT * FROM messages WHERE conversation_id=? "
                    "AND category=? AND public=1 AND (? IS NULL OR sequence<?) ORDER BY sequence DESC LIMIT 101",
                    ("app:workshop", CATEGORY, before, before)), 100, 180000)
                events = {row["id"]: delivery_events(history, row) for row in rows}
        from .workshop_mailbox import _routing
        messages = [{"id":row["id"], **_message_identity(row["author"], declared, self.binding.subject_root), "text":row["content"],
            "reply_to":row["reply_to"], "sequence":row["sequence"], "created_at":row["created_at"],
            "project": (_routing(row) or {}).get("project") or "",
            **project_injection_delivery(events[row["id"]], addressed=agent_addressed(row))}
            for row in reversed(rows)]
        return {"messages":messages, "more":more, "next_before":rows[-1]["sequence"] if rows else None}













    # WIRE-agents: parameters extend the current admitted graph and task owner.



















    # WIRE-agents end.


def _text(value):
    if type(value) is not str or not value.strip() or len(value.encode()) > 32000 or "\0" in value:
        raise ValueError("Task text must contain 1–32000 UTF-8 bytes")
    return value.strip()
