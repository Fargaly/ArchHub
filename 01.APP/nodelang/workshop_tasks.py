"""Workshop tasks: one table in the Workshop mailbox SQLite, claimed atomically.

Prior art: Paperclip issues.ts checkout. A claim is one conditional UPDATE; the row
changes only when it is free, its lease expired, or the claimant already holds it.
A lease that lapses frees the task for the next agent; nothing runs on a timer.
"""
import re
import time
from datetime import datetime, timezone
from hashlib import sha256
from uuid import uuid4

SCHEMA = ("CREATE TABLE IF NOT EXISTS workshop_tasks(id TEXT PRIMARY KEY, title TEXT NOT NULL, "
          "status TEXT NOT NULL CHECK(status IN ('open','claimed','done')), owner TEXT, owner_label TEXT, "
          "lease_until REAL, result TEXT, created_by TEXT NOT NULL, created_at TEXT NOT NULL, "
          "updated_at TEXT NOT NULL, session_path TEXT) STRICT")
TASKS_NODE = {'id': 'workshop.tasks', 'params': {'lease_seconds': 900}}
UI_STATUS = {"open": "PLANNED", "claimed": "WIP", "done": "DONE"}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _ensure(history):
    """The task table is the association: session_path is that task's .archhub file."""
    history._db.execute(SCHEMA)
    names = {row[1] for row in history._db.execute("PRAGMA table_info(workshop_tasks)")}
    if "session_path" not in names:
        history._db.execute("ALTER TABLE workshop_tasks ADD COLUMN session_path TEXT")
    if "archived" not in names:
        history._db.execute("ALTER TABLE workshop_tasks ADD COLUMN archived INTEGER NOT NULL DEFAULT 0")


def _write(history, sql, values):
    with history._transaction(write=True):
        _ensure(history)
        return history._db.execute(sql, values).rowcount == 1


def _text(value, label, maximum):
    if type(value) is not str or not value.strip() or "\0" in value or len(value.encode("utf-8")) > maximum:
        raise ValueError("Invalid task " + label)
    return value.strip()


def create(history, title, creator):
    task = uuid4().hex
    _write(history, "INSERT INTO workshop_tasks(id,title,status,created_by,created_at,updated_at) "
           "VALUES(?,?,'open',?,?,?)", (task, _text(title, "title", 2000), creator, _now(), _now()))
    return get(history, task)


def claim(history, task, owner, label, lease_seconds=None):
    """True when this owner holds the task after the call; False when another holds it."""
    lease_seconds = TASKS_NODE['params']['lease_seconds'] if lease_seconds is None else lease_seconds
    if type(lease_seconds) is not int or not 30 <= lease_seconds <= 86400:
        raise ValueError("Lease must be 30 to 86400 seconds")
    now = time.time()
    return _write(history, "UPDATE workshop_tasks SET status='claimed', owner=?, owner_label=?, lease_until=?, "
                  "updated_at=? WHERE id=? AND status!='done' AND (owner IS NULL OR owner=? OR lease_until<?)",
                  (owner, label, now + lease_seconds, _now(), task, owner, now))


def release(history, task, owner):
    return _write(history, "UPDATE workshop_tasks SET status='open', owner=NULL, owner_label=NULL, lease_until=NULL, "
                  "updated_at=? WHERE id=? AND owner=? AND status='claimed'", (_now(), task, owner))


def complete(history, task, owner, result=""):
    # The holder may finish after its lease lapsed, as long as nobody claimed it since.
    return _write(history, "UPDATE workshop_tasks SET status='done', lease_until=NULL, result=?, updated_at=? "
                  "WHERE id=? AND owner=? AND status='claimed'", (result, _now(), task, owner))


def archive(history, task):
    """Close a task so it leaves the active list. Its .archhub file stays readable."""
    if get(history, task) is None:
        raise ValueError("No such Workshop task")
    return _write(history, "UPDATE workshop_tasks SET status='done', archived=1, lease_until=NULL, updated_at=? WHERE id=?",
                  (_now(), task))


def declared(history, root, request_id, title, status, owner, label):
    """An agent's declare() is its task: working/blocked holds it, done completes it.

    Re-declaring renews the lease; a session that stops declaring lets it lapse.
    """
    task = "declared-" + sha256((root + "\0" + request_id).encode()).hexdigest()[:32]
    if status == "done":
        return complete(history, task, owner)
    _write(history, "INSERT INTO workshop_tasks(id,title,status,created_by,created_at,updated_at) "
           "VALUES(?,?,'open',?,?,?) ON CONFLICT(id) DO UPDATE SET title=excluded.title WHERE status!='done'",
           (task, _text(title, "title", 2000), label, _now(), _now()))
    # Moving to another request gives the previous declared task back to the pool.
    _write(history, "UPDATE workshop_tasks SET status='open', owner=NULL, owner_label=NULL, lease_until=NULL, "
           "updated_at=? WHERE owner=? AND status='claimed' AND id LIKE 'declared-%' AND id!=?", (_now(), owner, task))
    return claim(history, task, owner, label)


# A token that reads as an id, path, flag or measurement, not as words.
_JARGON = re.compile(r"[=/\\_<>{}`]|\d{3,}|[a-z][A-Z]|^[(\[]|^[A-Z][A-Z0-9]*-?\d|^[a-f0-9]{7,}$")
_TRAILING = {"in", "on", "at", "to", "for", "of", "and", "the", "a", "with", "from", "by"}


def short_title(text, limit=60):
    """A human task name: the first clause of the declared text without id/path tokens, at most `limit` chars."""
    text = re.sub(r"^\s*[A-Z0-9][A-Z0-9-]*:\s+", "", str(text or "").strip())  # a leading lane tag ("WSFIX: ")
    first = re.split(r"(?<=[.;:!?])\s|\n|\s[–—-]\s|\s\(", text, maxsplit=1)[0]
    words = [w for w in first.split() if not _JARGON.search(w)]
    while len(words) > 1 and words[-1].casefold() in _TRAILING:
        words.pop()
    title = " ".join(words).strip(" ,;:.-") or text[:limit]
    return title if len(title) <= limit else title[:limit - 1].rsplit(" ", 1)[0].rstrip(" ,;:.-") + "…"


def _thread_result(history, task):
    """The last Workshop message whose refs name this task. Empty when none was recorded."""
    if not history._db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='messages'").fetchone():
        return ""
    from .workshop_mailbox import ROOM
    found = history._db.execute(
        "SELECT content FROM messages WHERE conversation_id=? "
        "AND EXISTS (SELECT 1 FROM json_each(refs) WHERE value=?) ORDER BY sequence",
        (ROOM, task)).fetchall()
    return str(found[-1][0] or "").strip() if found else ""


def recorded_result(history, row):
    """The result the task stored, or the final reply that names it. Never a stand-in."""
    stored = row.get("result")
    if isinstance(stored, str) and stored.strip():
        return stored
    if row.get("status") != "done":
        return stored
    text = _thread_result(history, row["id"])
    return text if text else (stored if isinstance(stored, str) else "")


def _declaration_task_id(declaration):
    return "declared-" + sha256((declaration["root"] + "\0" + declaration["request_id"]).encode()).hexdigest()[:32]


def _session_context(path):
    """Task-session fields already stored in the task file. A missing file leaves them empty."""
    if not isinstance(path, str) or not path:
        return {}
    try:
        from .session_files import read_document
        document = read_document(path)
        context = _held_context(document)
    except (OSError, ValueError, KeyError, TypeError):
        return {}
    if context.get("scope") == document.get("id"):
        context["scope"] = ""
    context["fileMessages"] = _file_messages(document)
    return context


def column(history):
    """The Studio Work rows: a short name, the full declaration as details, and the owner's live state:
    Working while its session declares working or holds the lease, Needs you while it is blocked, Done when completed.
    Scope, agents, folders, session, plan and activity come from that declaration and the task file."""
    from .workshop_mailbox import read_declarations
    declarations = read_declarations(history._db, include_archived=True)
    by_task = {_declaration_task_id(item): item for item in declarations}
    live = {task_id: item["status"] for task_id, item in by_task.items() if item.get("current")}
    def state(row):
        if row["status"] == "done":
            return "DONE"
        if live.get(row["id"]) == "blocked":
            return "IN REVIEW"
        if live.get(row["id"]) == "working" or (row["status"] == "claimed" and not row["lease_expired"]):
            return "WIP"
        return "PLANNED"
    current = _current_session()
    found = []
    for row in rows(history, include_archived=False):
        declaration = by_task.get(row["id"])
        session = _session_context(row.get("session_path"))
        paths = [item for item in ((declaration or {}).get("paths") or []) if isinstance(item, str)]
        owner = row["owner_label"] if row["id"] in live or not row["lease_expired"] else None
        agents = [item for item in session.get("agents") or [] if isinstance(item, str) and item]
        label = owner or ((declaration or {}).get("agent") if declaration else None)
        if isinstance(label, str) and label and label not in agents:
            agents.insert(0, label)
        shown = state(row)
        plan = list(session.get("plan") or [])
        if not plan and (declaration or owner or shown in ("WIP", "IN REVIEW", "DONE")):
            plan = [{"title": short_title(row["title"]), "status": {"WIP": "working", "IN REVIEW": "blocked", "DONE": "done"}.get(shown, "")}]
        activity = list(session.get("activity") or [])
        if not activity and (declaration or row.get("result") or owner):
            activity = [{"id": row["id"], "status": shown, "output": row.get("result") or ""}]
        found.append({'id': row['id'], 'title': short_title(row['title']), 'description': row['title'],
             'owner': owner,
             'status': shown, 'result': recorded_result(history, row),
             'messages': [], 'fileMessages': list(session.get("fileMessages") or []), 'steps': [], 'reviews': [], 'queuedMessages': [],
             'declarations': [declaration] if declaration else [],
             'scope': session.get("scope") or (" · ".join(paths) if paths else ""),
             'rules': list(session.get("rules") or []),
             'agents': agents, 'folders': list(session.get("folders") or []) or paths,
             'references': list(session.get("references") or []),
             'session': row.get("session_path") or ((declaration or {}).get("session") if declaration else "") or "",
             'plan': plan, 'progress': session.get("progress") or {},
             'workflow': list(session.get("workflow") or []), 'activity': activity,
             'updated_at': row['updated_at'], 'sessionPath': row.get('session_path'),
             'sessionOpen': bool(row.get('session_path') and row['session_path'] == current)})
    return found


def set_status(history, task, status):
    """The founder's board move: PLANNED frees the task, DONE closes it, whoever holds it."""
    if status == "PLANNED":
        return _write(history, "UPDATE workshop_tasks SET status='open', owner=NULL, owner_label=NULL, "
                      "lease_until=NULL, updated_at=? WHERE id=?", (_now(), task))
    if status == "DONE":
        return _write(history, "UPDATE workshop_tasks SET status='done', lease_until=NULL, updated_at=? "
                      "WHERE id=?", (_now(), task))
    raise ValueError("An agent claims a task; the board sets PLANNED or DONE")


COLUMNS = ("id", "title", "status", "owner", "owner_label", "lease_until", "result",
           "created_by", "created_at", "updated_at", "session_path", "archived")


def rows(history, task=None, *, include_archived=True):
    if not history._db.execute("SELECT 1 FROM sqlite_master WHERE name='workshop_tasks'").fetchone():
        return []
    _ensure(history)
    now = time.time()
    # A lookup by id still finds an archived task. A list hides it unless asked.
    show = 1 if include_archived or task is not None else 0
    found = [dict(zip(COLUMNS, row)) for row in history._db.execute(
        "SELECT " + ",".join(COLUMNS) + " FROM workshop_tasks WHERE (? IS NULL OR id=?) "
        "AND (? OR IFNULL(archived,0)=0) ORDER BY created_at DESC LIMIT 500", (task, task, show))]
    for row in found:
        row["lease_expired"] = row["status"] == "claimed" and row["lease_until"] < now
    return found


def get(history, task):
    return next(iter(rows(history, task)), None)


def _current_session():
    """The file the canvas has open, recorded by the existing session-files owner."""
    import json
    import os
    from pathlib import Path
    root = Path(os.environ.get("LOCALAPPDATA") or "") / "ArchHub" / "sessions-files" / "current.json"
    try:
        held = json.loads(root.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return held.get("path") if isinstance(held, dict) and isinstance(held.get("path"), str) else ""


def _held_context(document):
    props = document.get("properties") if isinstance(document.get("properties"), dict) else {}
    held = props.get("taskContext") if isinstance(props.get("taskContext"), dict) else {}
    nodes = document.get("nodes") or []
    agents = list(held["agents"]) if isinstance(held.get("agents"), list) else []
    for node in nodes:
        if node.get("type") == "thing.agent":
            name = str((node.get("params") or {}).get("agent") or node.get("title") or "")
            if name and name not in agents:
                agents.append(name)
    return {
        "scope": held.get("scope") or document["id"],
        "rules": held["rules"] if isinstance(held.get("rules"), list) else [],
        "agents": agents,
        "plan": held["plan"] if isinstance(held.get("plan"), list) else [],
        "progress": held["progress"] if isinstance(held.get("progress"), dict) else {},
        "workflow": [{"id": node["id"], "type": node.get("type", ""), "title": node.get("title", "")} for node in nodes],
        "parameters": [{"id": node["id"], "params": node.get("params") or {}} for node in nodes],
        "activity": [{"id": node["id"], "status": node["result"].get("status", ""), "output": node["result"].get("output")}
                     for node in nodes if isinstance(node.get("result"), dict)],
        "folders": list(held["folders"]) if isinstance(held.get("folders"), list) else [],
        "references": list(held["references"]) if isinstance(held.get("references"), list) else [],
    }


_TASK_ROLE = "task"


def _task_message(note):
    """A task chat line is a note marked role task. Canvas annotations are not."""
    return isinstance(note, dict) and note.get("role") == _TASK_ROLE


def _file_messages(document):
    found = []
    for index, note in enumerate(document.get("notes") or []):
        if not _task_message(note) or not isinstance(note.get("text"), str):
            continue
        found.append({"id": note["id"] if isinstance(note.get("id"), str) and note["id"] else "note-%d" % index,
                      "role": _TASK_ROLE,
                      "who": note["who"] if isinstance(note.get("who"), str) and note["who"] else "Agent",
                      "text": note["text"]})
    return found


def _view(task, path, document):
    return {"id": document["id"], "path": path, "taskId": task, "messages": _file_messages(document), **_held_context(document)}


def _stamp(path, task, document):
    """Record which task this file belongs to. Scope, rules, agents, plan and progress already in it stay."""
    from .session_files import write_document
    props = dict(document.get("properties") or {})
    held = dict(props.get("taskContext") or {})
    held["task"] = task
    held.setdefault("scope", document["id"])
    props["taskContext"] = held
    document["properties"] = props
    write_document(path, document)
    return document


def _show(task, path, document, *, select=True):
    """Remember the file. Only an explicit open moves the canvas the founder has selected."""
    from .session_files import SessionFiles
    files = SessionFiles()
    files.remember(path, document)
    if select:
        files._current(document["id"], path)
    return _view(task, str(path), document)


def open_session(history, task, path=None, *, select=True):
    """Open this task's own .archhub file. A first path binds it; a later open reads that same file."""
    from .session_files import SessionFiles, local_path, new_document, read_document
    row = get(history, task)
    if row is None:
        raise ValueError("No such Workshop task")
    bound = row.get("session_path")
    if path is not None:
        target = str(local_path(path))
        if bound and bound != target:
            raise ValueError("Task already has a session file")
        holder = history._db.execute("SELECT id FROM workshop_tasks WHERE session_path=? AND id!=?", (target, task)).fetchone()
        if holder:
            raise ValueError("Session file belongs to another task")
        document = read_document(target)
        if not bound:
            document = _stamp(target, task, document)
            if not _write(history, "UPDATE workshop_tasks SET session_path=?, updated_at=? WHERE id=? AND session_path IS NULL",
                          (target, _now(), task)):
                raise ValueError("Task already has a session file")
        return _show(task, target, document, select=select)
    if bound:
        return _show(task, bound, read_document(bound), select=select)
    document = new_document(row["title"])
    target = str(local_path(str(SessionFiles().directory / (document["id"] + ".archhub"))))
    document = _stamp(target, task, document)
    if not _write(history, "UPDATE workshop_tasks SET session_path=?, updated_at=? WHERE id=? AND session_path IS NULL",
                  (target, _now(), task)):
        raise ValueError("Task already has a session file")
    return _show(task, target, document, select=select)


def create_session(history, title, creator="founder", *, select=True):
    """A new task and the .archhub file that holds its session."""
    row = create(history, title, creator)
    return open_session(history, row["id"], select=select)


_SESSION_FIELDS = {"scope", "rules", "agents", "plan", "progress", "nodes", "parameters", "messages", "folders", "references"}
_NODE_TYPES = {"note", "thing.agent"}
_SECRET_NAME = re.compile(r"(^|_)(password|secret|token|api_key|private_key|credential)(_|$)", re.I)


def _short_text(value, label, limit):
    if type(value) is not str or not value.strip() or "\0" in value or len(value) > limit:
        raise ValueError("Invalid task " + label)
    return value.strip()


def _plain(value, depth=0):
    if depth > 4:
        raise ValueError("Task value is too deep")
    if value is None or type(value) is bool or type(value) is str:
        if type(value) is str and (len(value) > 4000 or "\0" in value):
            raise ValueError("Task text is too long")
        return value
    if type(value) is int:
        return value
    if type(value) is float:
        if value != value or abs(value) == float("inf"):
            raise ValueError("Task number must be finite")
        return value
    if type(value) is list:
        if len(value) > 40:
            raise ValueError("Task list is too long")
        return [_plain(item, depth + 1) for item in value]
    if type(value) is dict:
        if len(value) > 40 or any(type(key) is not str or not key or len(key) > 80 for key in value):
            raise ValueError("Task object is too large")
        return {key: _plain(item, depth + 1) for key, item in value.items()}
    raise ValueError("Task value must be text, a number, or a short list")


def _text_list(value, label):
    if type(value) is not list or len(value) > 40:
        raise ValueError("Task " + label + " must be a short list")
    return [_short_text(item, label, 500) for item in value]


def _session_list(value, label):
    if type(value) is not list or len(value) > 40:
        raise ValueError("Task " + label + " must be a short list")
    return [_plain(item) for item in value]


def _merge_params(node, params):
    if type(params) is not dict or len(params) > 40:
        raise ValueError("Node parameters must be a short object")
    cleaned = {}
    for key, value in params.items():
        if type(key) is not str or not key or len(key) > 80 or "\0" in key or _SECRET_NAME.search(key):
            raise ValueError("Parameter name is invalid")
        cleaned[key] = _plain(value)
    node["params"] = {**node.get("params", {}), **cleaned}


def _apply_nodes(document, specs):
    if type(specs) is not list or len(specs) > 40:
        raise ValueError("Task nodes must be a short list")
    nodes = {node["id"]: node for node in document["nodes"]}
    for index, spec in enumerate(specs):
        if type(spec) is not dict or type(spec.get("id")) is not str or not spec["id"] or len(spec["id"]) > 80 or "\0" in spec["id"]:
            raise ValueError("Each node needs an id")
        kind = spec.get("type") or (nodes[spec["id"]]["type"] if spec["id"] in nodes else "note")
        if kind not in _NODE_TYPES:
            raise ValueError("Task node type must be note or thing.agent")
        node = nodes.get(spec["id"])
        if node is None:
            node = {"id": spec["id"], "type": kind, "title": spec.get("title") or spec["id"], "params": {},
                    "position": {"x": 48, "y": 48 + index * 72}}
            if kind == "thing.agent":
                node["params"] = {"agent": spec.get("title") or spec["id"], "instructions": ""}
                node["ports"] = {"source": [{"id": "result", "type": "any"}], "target": [{"id": "task", "type": "any"}]}
            document["nodes"].append(node)
            nodes[spec["id"]] = node
        elif spec.get("type") and node.get("type") != kind:
            raise ValueError("Node type is already set")
        if spec.get("title"):
            node["title"] = _short_text(spec["title"], "node title", 200)
        if "params" in spec:
            _merge_params(node, spec["params"])
        if "result" in spec:
            result = spec["result"]
            if type(result) is not dict:
                raise ValueError("Node result must be an object")
            node["result"] = {"status": _short_text(str(result.get("status") or "Idle"), "result status", 80),
                              "output": _plain(result.get("output")), "error": result.get("error") or ""}
            if type(node["result"]["error"]) is not str or len(node["result"]["error"]) > 500:
                raise ValueError("Node result error must be short text")


def _apply_parameters(document, rows):
    if type(rows) is not list or len(rows) > 40:
        raise ValueError("Parameters must name nodes")
    nodes = {node["id"]: node for node in document["nodes"]}
    for row in rows:
        if type(row) is not dict or row.get("id") not in nodes:
            raise ValueError("Parameter names a node that is not in this task")
        _merge_params(nodes[row["id"]], row.get("params"))


def _apply_messages(document, rows):
    if type(rows) is not list or len(rows) > 80:
        raise ValueError("Task messages must be a short list")
    messages = []
    for index, row in enumerate(rows):
        if type(row) is not dict:
            raise ValueError("Each message needs text")
        text = _short_text(row.get("text"), "message", 4000)
        who = _short_text(row.get("who") or "Agent", "message author", 80)
        note_id = row.get("id") if type(row.get("id")) is str and row["id"] and len(row["id"]) <= 80 else "msg-%d" % index
        messages.append({"id": note_id, "role": _TASK_ROLE, "who": who, "text": text})
    kept = [note for note in (document.get("notes") or []) if not _task_message(note)]
    document["notes"] = kept + messages


def update_session(history, task, values):
    """Write this task's parameters, plan, agents and progress into its .archhub file."""
    from .session_files import read_document, validate, write_document
    if type(values) is not dict or set(values) - _SESSION_FIELDS:
        raise ValueError("Unsupported task session fields")
    row = get(history, task)
    if row is None:
        raise ValueError("No such Workshop task")
    if not row.get("session_path"):
        open_session(history, task, select=False)
        row = get(history, task)
    path = row["session_path"]
    document = read_document(path)
    props = dict(document.get("properties") or {})
    held = dict(props.get("taskContext") or {})
    if "scope" in values:
        held["scope"] = _short_text(values["scope"], "scope", 200)
    if "rules" in values:
        held["rules"] = _text_list(values["rules"], "rules")
    if "agents" in values:
        held["agents"] = _text_list(values["agents"], "agents")
    if "plan" in values:
        held["plan"] = _text_list(values["plan"], "plan")
    if "folders" in values:
        held["folders"] = _session_list(values["folders"], "folders")
    if "references" in values:
        held["references"] = _session_list(values["references"], "references")
    if "progress" in values:
        progress = values["progress"]
        if type(progress) is not dict:
            raise ValueError("Task progress must be an object")
        held["progress"] = _plain(progress)
    held["task"] = task
    props["taskContext"] = held
    document["properties"] = props
    if "nodes" in values:
        _apply_nodes(document, values["nodes"])
    if "parameters" in values:
        _apply_parameters(document, values["parameters"])
    if "messages" in values:
        _apply_messages(document, values["messages"])
    validate(document)
    write_document(path, document)
    return _show(task, path, read_document(path), select=False)
